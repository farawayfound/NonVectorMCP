# -*- coding: utf-8 -*-
"""ChunkyPotato — FastAPI application entry point."""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import get_settings
from backend.database import init_db_sync
from backend.logger import log_event, set_session
from backend.chat.ollama_client import init_ollama_http, close_ollama_http, ensure_single_model_loaded


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        client_ip = request.client.host if request.client else ""
        session = {
            "request_id": uuid.uuid4().hex[:12],
            "client_ip": client_ip,
            "user_agent": request.headers.get("user-agent", ""),
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


async def _model_keepalive() -> None:
    """Keep the configured Ollama model warm.

    Every few minutes, ensures only the configured model is loaded (evict others)
    and preloads it if missing. Skips redundant /api/generate preloads when the
    model is already in memory. Uses exponential back-off if Ollama isn't
    reachable yet (common right after system boot).
    """
    await asyncio.sleep(5)  # let the app fully start before first ping
    retry_delay = 30
    while True:
        try:
            settings = get_settings()
            await ensure_single_model_loaded(settings.OLLAMA_MODEL)
            retry_delay = 30  # reset back-off after a success
            await asyncio.sleep(240)  # ping every 4 minutes
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("keepalive: ping failed (%s) — retrying in %ss", exc, retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 240)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Ensure data directories exist
    for d in [settings.INDEXES_DIR / "demo" / "detail",
              settings.INDEXES_DIR / "demo" / "router",
              settings.INDEXES_DIR / "demo" / "state",
              settings.UPLOADS_DIR / "demo",
              settings.DB_PATH.parent,
              settings.LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    # Initialize database
    init_db_sync()
    await init_ollama_http()
    # Warm model as soon as Ollama is up (first chat request avoids cold load)
    try:
        await ensure_single_model_loaded(settings.OLLAMA_MODEL)
        log_event("ollama_startup_warm", model=settings.OLLAMA_MODEL)
    except Exception as exc:
        logging.warning("ollama startup warm failed (keepalive will retry): %s", exc)
    # Keep the Ollama model warm so first-token latency stays predictable
    keepalive_task = asyncio.create_task(_model_keepalive())
    yield
    keepalive_task.cancel()
    try:
        await keepalive_task
    except asyncio.CancelledError:
        pass
    await close_ollama_http()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ChunkyPotato",
        description="Self-hostable document RAG system",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AccessLogMiddleware)

    # Import and include routers
    from backend.routes import auth, chat, documents, index, admin
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    app.include_router(index.router, prefix="/api/index", tags=["index"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "chunkylink"}

    # Serve the pre-built React frontend if the dist/ folder exists.
    # This lets uvicorn run as a single process without a separate nginx.
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        def serve_index() -> FileResponse:
            # Avoid stale SPA shell after deploys (hashed asset names change).
            return FileResponse(
                str(dist / "index.html"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Serve real files that exist (favicon, robots.txt, etc.)
            candidate = dist / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # Everything else → index.html (SPA client-side routing)
            return serve_index()

    return app


app = create_app()
