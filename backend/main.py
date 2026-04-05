# -*- coding: utf-8 -*-
"""ChunkyLink — FastAPI application entry point."""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import get_settings
from backend.database import init_db_sync
from backend.logger import log_event, set_session


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

    Sends a keep_alive=-1 preload ping on startup and then every 4 minutes so
    Ollama never evicts the model from memory.  Uses exponential back-off if
    Ollama isn't reachable yet (common right after system boot).
    """
    from backend.chat.ollama_client import ensure_single_model_loaded
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
    # Keep the Ollama model warm so first-token latency is always minimal
    keepalive_task = asyncio.create_task(_model_keepalive())
    yield
    keepalive_task.cancel()
    try:
        await keepalive_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ChunkyLink",
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

    return app


app = create_app()
