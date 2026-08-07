from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from file_store import FileStore, FileStoreError, StoredFile
from memory_store import MemoryStore, MemoryStoreError


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _public_base_url() -> str:
    value = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or "http://127.0.0.1:8000"
    )
    return value.rstrip("/")


BASE_URL = _public_base_url()
TTL_SECONDS = max(60, _env_int("FILE_TTL_HOURS", 24) * 60 * 60)
MAX_CONTENT_BYTES = max(1024, _env_int("MAX_CONTENT_BYTES", 3_000_000))
GENERATED_DIR = Path(os.getenv("GENERATED_DIR", "/tmp/kelivo-file-mcp/generated_files"))

store = FileStore(
    root=GENERATED_DIR,
    base_url=BASE_URL,
    ttl_seconds=TTL_SECONDS,
    max_content_bytes=MAX_CONTENT_BYTES,
)

memory_store = MemoryStore(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SECRET_KEY"),
)

mcp = MCPServer("Kelivo File Maker")


def _result(item: StoredFile) -> str:
    return f"文件已生成\n文件名：{item.filename}\n下载地址：{item.download_url}"


def _error(exc: Exception) -> str:
    return f"生成失败：{exc}"


def _cleanup() -> None:
    try:
        store.cleanup_expired()
    except Exception:
        # Cleanup failure must never block file creation/download.
        pass


@mcp.tool()
def create_txt(filename: str, content: str) -> str:
    """把完整文本或代码生成 UTF-8 TXT 文件，并返回可下载地址。"""
    _cleanup()
    try:
        return _result(store.create_text_file(filename, content, ".txt"))
    except FileStoreError as exc:
        return _error(exc)


@mcp.tool()
def create_html(filename: str, content: str) -> str:
    """把完整 HTML 源码生成 UTF-8 HTML 文件，并返回可下载地址。"""
    _cleanup()
    try:
        return _result(store.create_text_file(filename, content, ".html"))
    except FileStoreError as exc:
        return _error(exc)


@mcp.tool()
def create_pair(filename: str, content: str) -> str:
    """用完全相同的源码同时生成 TXT 和 HTML 两份文件。"""
    _cleanup()
    try:
        txt, html = store.create_pair(filename, content)
    except FileStoreError as exc:
        return _error(exc)
    return (
        "文件已生成（两份源码内容完全一致）\n"
        f"TXT：{txt.download_url}\n"
        f"HTML：{html.download_url}"
    )


@mcp.tool()
def create_file(filename: str, content: str) -> str:
    """生成指定文本文件。支持 txt/html/htm/md/css/js/json/xml/csv/yaml/yml。"""
    _cleanup()
    try:
        return _result(store.create_file(filename, content))
    except FileStoreError as exc:
        return _error(exc)



def _memory_error(exc: Exception) -> str:
    return f"记忆操作失败：{exc}"


def _memory_rows(rows: list[dict]) -> str:
    if not rows:
        return "没有找到长期记忆"
    lines = [f"找到 {len(rows)} 条长期记忆："]
    for index, row in enumerate(rows, start=1):
        category = str(row.get("category", ""))
        key = str(row.get("key", ""))
        content = str(row.get("content", ""))
        keywords = str(row.get("keywords", ""))
        updated_at = str(row.get("updated_at", ""))
        lines.append(f"[{index}] {category}/{key}")
        lines.append(f"内容：{content}")
        if keywords:
            lines.append(f"关键词：{keywords}")
        if updated_at:
            lines.append(f"更新时间：{updated_at}")
    return "\n".join(lines)


@mcp.tool()
def memory_search(query: str, category: str = "", limit: int = 8) -> str:
    """按当前任务检索相关长期记忆。category 可留空，limit 默认 8。"""
    try:
        return _memory_rows(memory_store.search(query, category, limit))
    except MemoryStoreError as exc:
        return _memory_error(exc)


@mcp.tool()
def memory_get_all(category: str = "") -> str:
    """读取全部长期记忆，或读取指定 category 下的全部记忆。"""
    try:
        return _memory_rows(memory_store.get_all(category))
    except MemoryStoreError as exc:
        return _memory_error(exc)


@mcp.tool()
def memory_add(category: str, key: str, content: str, keywords: str = "") -> str:
    """保存明确的长期规则；相同 category/key 已存在时自动覆盖旧内容。"""
    try:
        row = memory_store.add(category, key, content, keywords)
    except MemoryStoreError as exc:
        return _memory_error(exc)
    return (
        "长期记忆已保存\n"
        f"标识：{row.get('category', category)}/{row.get('key', key)}\n"
        f"内容：{row.get('content', content)}"
    )


@mcp.tool()
def memory_update(category: str, key: str, content: str, keywords: str = "") -> str:
    """显式更新一条已存在的长期记忆。"""
    try:
        row = memory_store.update(category, key, content, keywords)
    except MemoryStoreError as exc:
        return _memory_error(exc)
    return (
        "长期记忆已更新\n"
        f"标识：{row.get('category', category)}/{row.get('key', key)}\n"
        f"内容：{row.get('content', content)}"
    )


@mcp.tool()
def memory_delete(category: str, key: str) -> str:
    """删除用户明确要求忘记的一条长期记忆。"""
    try:
        deleted = memory_store.delete(category, key)
    except MemoryStoreError as exc:
        return _memory_error(exc)
    if not deleted:
        return f"没有找到要删除的长期记忆：{category}/{key}"
    return f"长期记忆已删除：{category}/{key}"


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse(
        {
            "status": "ok",
            "service": "Kelivo File Maker MCP",
            "mcp": "/mcp",
            "ttl_hours": TTL_SECONDS // 3600,
            "max_content_bytes": MAX_CONTENT_BYTES,
            "memory_configured": memory_store.configured,
        }
    )


@mcp.custom_route("/download/{token}/{filename}", methods=["GET"])
async def download(request: Request) -> Response:
    _cleanup()
    token = request.path_params.get("token", "")
    filename = request.path_params.get("filename", "")
    path = store.resolve_download(token, filename)
    if path is None:
        return JSONResponse(
            {"error": "文件不存在、已过期或下载地址无效"},
            status_code=404,
        )
    media_type = mimetypes.guess_type(filename)[0] or "text/plain"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
    )


# Render sits behind a reverse proxy that controls the public hostname.
# The MCP SDK docs explicitly permit disabling DNS-rebinding protection in
# that situation. Local development keeps the SDK's host protection enabled.
if os.getenv("RENDER", "").lower() == "true":
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
else:
    transport_security = TransportSecuritySettings(
        allowed_hosts=[
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "[::1]",
            "[::1]:*",
        ],
        allowed_origins=[
            "http://localhost",
            "http://localhost:*",
            "http://127.0.0.1",
            "http://127.0.0.1:*",
        ],
    )

app = mcp.streamable_http_app(transport_security=transport_security)
