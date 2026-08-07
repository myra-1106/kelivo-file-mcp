from __future__ import annotations

import shutil
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class FileStoreError(ValueError):
    """User-correctable file-generation error."""


@dataclass(frozen=True)
class StoredFile:
    token: str
    filename: str
    path: Path
    download_url: str


class FileStore:
    ALLOWED_EXTENSIONS = {
        ".txt",
        ".html",
        ".htm",
        ".md",
        ".css",
        ".js",
        ".json",
        ".xml",
        ".csv",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        root: str | Path,
        base_url: str,
        ttl_seconds: int = 24 * 60 * 60,
        max_content_bytes: int = 3_000_000,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_content_bytes = max(1, int(max_content_bytes))

    def create_text_file(self, filename: str, content: str, extension: str) -> StoredFile:
        extension = self._normalize_extension(extension)
        token = uuid.uuid4().hex
        safe_name = self._force_extension(self._sanitize_filename(filename), extension)
        return self._write(token, safe_name, content)

    def create_pair(self, filename: str, content: str) -> tuple[StoredFile, StoredFile]:
        self._validate_content(content)
        token = uuid.uuid4().hex
        base = self._strip_known_extension(self._sanitize_filename(filename))
        txt = self._write(token, f"{base}.txt", content, validate=False)
        html = self._write(token, f"{base}.html", content, validate=False)
        return txt, html

    def create_file(self, filename: str, content: str) -> StoredFile:
        safe_name = self._sanitize_filename(filename)
        extension = Path(safe_name).suffix.lower()
        if extension not in self.ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(self.ALLOWED_EXTENSIONS))
            raise FileStoreError(f"不支持的文件扩展名：{extension or '无'}。允许：{allowed}")
        token = uuid.uuid4().hex
        return self._write(token, safe_name, content)

    def resolve_download(self, token: str, filename: str) -> Path | None:
        if not token or any(ch not in "0123456789abcdef" for ch in token.lower()) or len(token) != 32:
            return None
        safe_name = self._sanitize_filename(filename)
        if safe_name != filename:
            return None
        candidate = (self.root / token / safe_name).resolve()
        expected_parent = (self.root / token).resolve()
        if candidate.parent != expected_parent or not candidate.is_file():
            return None
        return candidate

    def cleanup_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        if not self.root.exists():
            return removed
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            try:
                age = now - child.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > self.ttl_seconds:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed

    def _write(self, token: str, filename: str, content: str, validate: bool = True) -> StoredFile:
        if validate:
            self._validate_content(content)
        bundle = self.root / token
        bundle.mkdir(parents=True, exist_ok=True)
        path = bundle / filename
        path.write_text(content, encoding="utf-8", newline="")
        url = f"{self.base_url}/download/{quote(token)}/{quote(filename)}"
        return StoredFile(token=token, filename=filename, path=path, download_url=url)

    def _validate_content(self, content: str) -> None:
        if not isinstance(content, str):
            raise FileStoreError("content 必须是文本字符串")
        size = len(content.encode("utf-8"))
        if size > self.max_content_bytes:
            raise FileStoreError(
                f"内容过大：{size} bytes，当前上限 {self.max_content_bytes} bytes"
            )

    @classmethod
    def _normalize_extension(cls, extension: str) -> str:
        extension = str(extension or "").strip().lower()
        if not extension.startswith("."):
            extension = "." + extension
        if extension not in cls.ALLOWED_EXTENSIONS:
            raise FileStoreError(f"不支持的文件扩展名：{extension}")
        return extension

    @classmethod
    def _sanitize_filename(cls, filename: str) -> str:
        raw = unicodedata.normalize("NFC", str(filename or "").strip())
        raw = Path(raw.replace("\\", "/")).name
        raw = "".join(ch for ch in raw if ch >= " " and ch not in {"\x7f", "\x00"})
        raw = raw.strip(" .")
        if not raw:
            raw = "generated"
        if raw in {".", ".."}:
            raw = "generated"
        if len(raw) > 160:
            suffix = Path(raw).suffix
            stem_limit = max(1, 160 - len(suffix))
            raw = Path(raw).stem[:stem_limit] + suffix
        return raw

    @classmethod
    def _strip_known_extension(cls, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix in cls.ALLOWED_EXTENSIONS:
            filename = filename[: -len(suffix)]
        filename = filename.rstrip(" .")
        return filename or "generated"

    @classmethod
    def _force_extension(cls, filename: str, extension: str) -> str:
        if filename.lower().endswith(extension):
            return filename
        suffix = Path(filename).suffix.lower()
        if suffix in cls.ALLOWED_EXTENSIONS:
            filename = filename[: -len(suffix)]
        return f"{filename}{extension}"
