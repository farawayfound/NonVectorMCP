# -*- coding: utf-8 -*-
"""MCP HTTP server — exposes search_kb, search_jira, build_index tools."""
import json, re, time, uuid, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from tools import search_kb, search_jira, build_index as build_tool, learn as learn_tool
from logger import log_event, set_session
import config

mcp = FastMCP("vpoRAG", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=False
))
mcp.tool(name="search_kb")(search_kb.run)
mcp.tool(name="search_jira")(search_jira.run)
mcp.tool(name="build_index")(build_tool.run)
mcp.tool(name="learn")(learn_tool.run)

# ── Dynamic token registry ────────────────────────────────────────────────────
# Sidecar file for auto-registered tokens — merged with AUTH_TOKENS at startup.
_SIDECAR = Path(__file__).parent / "auth_tokens.json"
_TOKEN_PATTERN = re.compile(r'^vporag-P\d{7}$', re.IGNORECASE)

def _load_dynamic_tokens() -> dict:
    if _SIDECAR.exists():
        try:
            return json.loads(_SIDECAR.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

_dynamic_tokens: dict = _load_dynamic_tokens()

def _all_tokens() -> dict:
    """Merged view: static config tokens take precedence over dynamic ones."""
    merged = dict(_dynamic_tokens)
    merged.update(getattr(config, "AUTH_TOKENS", {}))
    return merged

def _try_auto_register(token: str, client_ip: str) -> str | None:
    """If token matches vporag-P<7digits>, register it and return the user_id."""
    if not _TOKEN_PATTERN.match(token):
        return None
    user_id = token[len("vporag-"):].upper()   # e.g. "vporag-p3315113" → "P3315113"
    _dynamic_tokens[token] = user_id
    try:
        _SIDECAR.write_text(
            json.dumps(_dynamic_tokens, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        import logging
        logging.warning(f"auto-register: could not write sidecar: {e}")
    log_event("user_registered", token=token, user_id=user_id, client_ip=client_ip)
    return user_id


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        require_auth = getattr(config, "REQUIRE_AUTH", False)
        auth_header  = request.headers.get("authorization", "")
        token        = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        client_ip    = request.client.host if request.client else ""

        if token:
            user_id = _all_tokens().get(token)
            if user_id is None:
                user_id = _try_auto_register(token, client_ip) or "anonymous"
        else:
            user_id = "anonymous"

        if require_auth and user_id == "anonymous":
            from starlette.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        session = {
            "request_id":     uuid.uuid4().hex[:12],
            "client_ip":      client_ip,
            "client_port":    request.client.port if request.client else None,
            "user_agent":     request.headers.get("user-agent", ""),
            "mcp_session_id": request.headers.get("mcp-session-id", ""),
            "user_id":        user_id,
        }
        set_session(session)
        log_event("request_start", method=request.method, path=str(request.url.path))
        try:
            response = await call_next(request)
            log_event("request_end",
                      http_status=response.status_code,
                      duration_ms=round((time.monotonic() - t0) * 1000))
            return response
        except Exception as ex:
            log_event("request_error",
                      error_type=type(ex).__name__, error=str(ex),
                      duration_ms=round((time.monotonic() - t0) * 1000))
            raise


# ── Accept-header shim ───────────────────────────────────────────────────────
# Amazon Q's MCP client sends Accept: application/json on the initial POST.
# mcp 1.26.0 requires both application/json AND text/event-stream or returns 406.
# This raw ASGI middleware injects text/event-stream before the MCP app sees it.
class _AcceptShim:
    def __init__(self, inner):
        self._inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST":
            headers = {k: v for k, v in scope.get("headers", [])}
            accept = headers.get(b"accept", b"").decode()
            if "text/event-stream" not in accept:
                patched = (accept + ", text/event-stream").lstrip(", ").encode()
                new_headers = [(k, patched if k == b"accept" else v)
                               for k, v in scope.get("headers", [])]
                if b"accept" not in headers:
                    new_headers.append((b"accept", patched))
                scope = dict(scope, headers=new_headers)
        await self._inner(scope, receive, send)


_mcp_app = mcp.streamable_http_app()
_mcp_app.add_middleware(AccessLogMiddleware)
app = _AcceptShim(_mcp_app)


# ── Startup chunk cache warm-up ───────────────────────────────────────────────
# Preload all 33K chunks into search_kb._CHUNK_CACHE in a background thread
# so the first tool call never pays the 8s I/O cost.
def _warmup_chunk_cache() -> None:
    import logging, threading
    from pathlib import Path
    def _warm():
        try:
            kb_dir = Path(config.JSON_KB_DIR)
            from tools.search_kb import (
                _load_all_category_chunks, _filter_domain_chunks,
                _set_cached_chunks, _DEFAULT_DOMAINS,
            )
            all_chunks = _load_all_category_chunks(kb_dir)
            domain_chunks, _ = _filter_domain_chunks(all_chunks, _DEFAULT_DOMAINS)
            _set_cached_chunks(kb_dir, _DEFAULT_DOMAINS, domain_chunks, all_chunks)
            logging.info(f"startup: chunk cache warmed ({len(all_chunks)} chunks)")
        except Exception as e:
            logging.warning(f"startup: chunk cache warm-up failed: {e}")
    threading.Thread(target=_warm, daemon=True, name="chunk-warmup").start()

_warmup_chunk_cache()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)