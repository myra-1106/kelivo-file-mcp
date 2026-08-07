from __future__ import annotations

import re
from typing import Any

import httpx


class MemoryStoreError(RuntimeError):
    """Raised when durable memory storage cannot complete an operation."""


class MemoryStore:
    def __init__(
        self,
        url: str | None,
        secret_key: str | None,
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = (url or "").strip().rstrip("/")
        self.secret_key = (secret_key or "").strip()
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret_key)

    def _ensure_configured(self) -> None:
        if not self.url or not self.secret_key:
            raise MemoryStoreError(
                "全局记忆未配置：需要同时设置 SUPABASE_URL 和 SUPABASE_SECRET_KEY"
            )

    def _client(self) -> httpx.Client:
        self._ensure_configured()
        # Supabase's new sb_secret_* keys are opaque API keys, not JWTs.
        # They must be sent in the apikey header rather than Authorization: Bearer.
        return httpx.Client(
            base_url=self.url,
            headers={
                "apikey": self.secret_key,
                "accept": "application/json",
            },
            timeout=self.timeout_seconds,
            transport=self._transport,
        )

    def _safe_error_text(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                text = str(payload.get("message") or payload.get("error") or payload)
            else:
                text = str(payload)
        except Exception:
            text = response.text or f"HTTP {response.status_code}"
        if self.secret_key:
            text = text.replace(self.secret_key, "[REDACTED]")
        return text[:500]

    def _request(self, method: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._client() as client:
                response = client.request(method, "/rest/v1/memories", **kwargs)
        except MemoryStoreError:
            raise
        except httpx.HTTPError as exc:
            raise MemoryStoreError(f"Supabase 请求失败：{exc}") from exc
        if response.status_code >= 400:
            raise MemoryStoreError(
                f"Supabase 返回 HTTP {response.status_code}：{self._safe_error_text(response)}"
            )
        return response

    @staticmethod
    def _require_text(name: str, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise MemoryStoreError(f"{name} 不能为空")
        return cleaned

    @staticmethod
    def _rows(response: httpx.Response) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except Exception as exc:
            raise MemoryStoreError("Supabase 返回了无法解析的 JSON") from exc
        if not isinstance(payload, list):
            raise MemoryStoreError("Supabase 返回的数据格式不正确")
        return [row for row in payload if isinstance(row, dict)]

    def get_all(self, category: str = "") -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "select": "id,category,key,content,keywords,created_at,updated_at",
            "order": "updated_at.desc",
            "limit": 1000,
        }
        category = (category or "").strip()
        if category:
            params["category"] = f"eq.{category}"
        response = self._request("GET", params=params)
        return self._rows(response)

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        normalized = query.casefold().strip()
        if not normalized:
            return []

        terms: set[str] = set()
        for token in re.findall(r"[a-z0-9_.-]+|[\u3400-\u9fff]+", normalized):
            if not token:
                continue
            terms.add(token)
            if re.fullmatch(r"[\u3400-\u9fff]+", token) and len(token) > 2:
                terms.update(token[i : i + 2] for i in range(len(token) - 1))
        return sorted(terms, key=len, reverse=True)

    @classmethod
    def _score(cls, row: dict[str, Any], query: str) -> int:
        normalized = query.casefold().strip()
        fields = {
            "key": str(row.get("key", "")).casefold(),
            "keywords": str(row.get("keywords", "")).casefold(),
            "category": str(row.get("category", "")).casefold(),
            "content": str(row.get("content", "")).casefold(),
        }
        if not normalized:
            return 1

        score = 0
        full_weights = {"key": 80, "keywords": 70, "category": 60, "content": 50}
        term_weights = {"key": 12, "keywords": 10, "category": 8, "content": 6}

        for name, text in fields.items():
            if normalized in text:
                score += full_weights[name]

        for term in cls._query_terms(normalized):
            for name, text in fields.items():
                if term in text:
                    score += term_weights[name] + min(len(term), 12)
        return score

    def search(self, query: str, category: str = "", limit: int = 8) -> list[dict[str, Any]]:
        query = (query or "").strip()
        category = (category or "").strip()
        try:
            limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError("limit 必须是整数") from exc
        limit = max(1, min(limit, 50))

        rows = self.get_all(category)
        scored = [(self._score(row, query), row) for row in rows]
        if query:
            scored = [(score, row) for score, row in scored if score > 0]
        scored.sort(
            key=lambda item: (item[0], str(item[1].get("updated_at", ""))),
            reverse=True,
        )
        return [row for _, row in scored[:limit]]

    def add(self, category: str, key: str, content: str, keywords: str = "") -> dict[str, Any]:
        category = self._require_text("category", category)
        key = self._require_text("key", key)
        content = self._require_text("content", content)
        payload = {
            "category": category,
            "key": key,
            "content": content,
            "keywords": (keywords or "").strip(),
        }
        response = self._request(
            "POST",
            params={"on_conflict": "category,key"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json=payload,
        )
        rows = self._rows(response)
        if not rows:
            raise MemoryStoreError("Supabase 未返回新增或更新后的记忆")
        return rows[0]

    def update(self, category: str, key: str, content: str, keywords: str = "") -> dict[str, Any]:
        category = self._require_text("category", category)
        key = self._require_text("key", key)
        content = self._require_text("content", content)
        response = self._request(
            "PATCH",
            params={"category": f"eq.{category}", "key": f"eq.{key}"},
            headers={"Prefer": "return=representation"},
            json={"content": content, "keywords": (keywords or "").strip()},
        )
        rows = self._rows(response)
        if not rows:
            raise MemoryStoreError(f"没有找到要更新的记忆：{category}/{key}")
        return rows[0]

    def delete(self, category: str, key: str) -> bool:
        category = self._require_text("category", category)
        key = self._require_text("key", key)
        response = self._request(
            "DELETE",
            params={"category": f"eq.{category}", "key": f"eq.{key}"},
            headers={"Prefer": "return=representation"},
        )
        return bool(self._rows(response))
