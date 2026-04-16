# -*- coding: utf-8 -*-
"""ChunkyPotato — FastAPI application entry point."""
import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import get_settings
from backend.database import init_db_sync
from backend.logger import log_event, set_session
from backend.chat.ollama_client import (
    init_ollama_http,
    close_ollama_http,
    ensure_single_model_loaded,
    ensure_single_model_loaded_at_base,
)


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


INACTIVITY_CLEANUP_MINUTES = 1440  # 24h — lets users step away during long index builds


def _frontend_dist_probe(*, include_git: bool = True) -> dict:
    """Resolved SPA dist path, bundle name, and optional git HEAD for deploy debugging."""
    repo = Path(__file__).resolve().parent.parent
    dist_index = repo / "frontend" / "dist" / "index.html"
    main_js = None
    if dist_index.is_file():
        txt = dist_index.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'src="(/assets/[^"]+\.js)"', txt)
        if m:
            main_js = m.group(1)
    mtime = int(dist_index.stat().st_mtime) if dist_index.is_file() else None
    git_head = None
    if include_git:
        try:
            import subprocess

            gr = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if gr.returncode == 0:
                git_head = gr.stdout.strip()
        except Exception:
            pass
    return {
        "repo_root": str(repo),
        "process_cwd": str(Path.cwd()),
        "dist_index_exists": dist_index.is_file(),
        "dist_index_mtime_unix": mtime,
        "dist_main_js": main_js,
        "git_head_short": git_head,
    }


async def _session_cleanup() -> None:
    """Periodically clean up expired sessions and inactive user data.

    Runs every 5 minutes. Removes data for users whose sessions have expired
    or who have been inactive for more than INACTIVITY_CLEANUP_MINUTES,
    unless they opted to preserve their data.
    """
    await asyncio.sleep(60)  # wait for app startup
    while True:
        try:
            from backend.database import get_db
            from backend.storage import should_preserve_user_data, delete_user_data
            from backend.storage import get_user_upload_dir

            db = await get_db()
            try:
                now = datetime.now(timezone.utc)

                # 1) Find expired sessions and clean up their user data
                cursor = await db.execute(
                    "SELECT DISTINCT user_id FROM sessions WHERE expires_at < ?",
                    (now.isoformat(),),
                )
                expired_rows = await cursor.fetchall()
                for row in expired_rows:
                    uid = dict(row)["user_id"]
                    if not should_preserve_user_data(uid):
                        delete_user_data(uid)
                        logging.info("cleanup: wiped data for expired session user %s", uid)
                # Delete the expired session rows
                await db.execute(
                    "DELETE FROM sessions WHERE expires_at < ?",
                    (now.isoformat(),),
                )
                await db.commit()

                # 2) Find users inactive for > INACTIVITY_CLEANUP_MINUTES with
                #    active sessions but who have uploaded documents
                cutoff = (now - timedelta(minutes=INACTIVITY_CLEANUP_MINUTES)).isoformat()
                cursor = await db.execute(
                    "SELECT DISTINCT s.user_id FROM sessions s "
                    "JOIN users u ON s.user_id = u.id "
                    "WHERE u.last_seen < ? AND s.expires_at >= ?",
                    (cutoff, now.isoformat()),
                )
                inactive_rows = await cursor.fetchall()
                for row in inactive_rows:
                    uid = dict(row)["user_id"]
                    if not should_preserve_user_data(uid):
                        # Only clean if user actually has uploaded data
                        upload_dir = get_user_upload_dir(uid)
                        has_files = any(
                            f.is_file() and not f.name.startswith(".")
                            for f in upload_dir.iterdir()
                        ) if upload_dir.exists() else False
                        if has_files:
                            delete_user_data(uid)
                            logging.info("cleanup: wiped data for inactive user %s (>%d min)",
                                         uid, INACTIVITY_CLEANUP_MINUTES)
                await db.commit()
            finally:
                await db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("session_cleanup: error — %s", exc)
        await asyncio.sleep(300)  # run every 5 minutes


async def _reconcile_library_tasks() -> None:
    """Periodically reconcile library tasks stuck in active states.

    If the browser SSE connection was closed before the worker published its
    terminal status (failed / review), the DB row is never updated.  This loop
    reads the Redis status stream for all active tasks every 30 s and promotes
    them to the correct terminal state so the UI always shows the real outcome.
    """
    from backend.library.service import reconcile_active_tasks
    await asyncio.sleep(15)  # let startup finish before first run
    while True:
        try:
            await reconcile_active_tasks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.debug("library reconcile loop: %s", exc)
        await asyncio.sleep(30)


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
              settings.UPLOADS_DIR / "media",
              settings.DB_PATH.parent,
              settings.LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    # Initialize database
    init_db_sync()
    await init_ollama_http()
    # Connect Redis queue for Library. We try once up-front and, on failure,
    # keep retrying in a background task so the feature recovers automatically
    # if redis comes up after the backend (systemd start order, brew services,
    # docker-compose race, etc.) without requiring a service restart.
    from backend.library.queue import init_queue, close_queue as _close_queue, get_queue
    redis_reconnect_task: asyncio.Task | None = None
    try:
        await init_queue(settings.REDIS_URL)
        log_event("redis_connected", url=settings.REDIS_URL)
    except Exception as exc:
        logging.error(
            "redis queue init failed — Library research will fail until redis is reachable "
            "at %s (%s). Background reconnect loop started.",
            settings.REDIS_URL, exc,
        )

        async def _redis_reconnect_loop() -> None:
            delay = 2.0
            while True:
                try:
                    await asyncio.sleep(delay)
                    get_queue()  # already connected? nothing to do
                    return
                except RuntimeError:
                    pass
                try:
                    await init_queue(settings.REDIS_URL)
                    log_event("redis_connected", url=settings.REDIS_URL, reconnected=True)
                    logging.info("redis queue reconnected at %s", settings.REDIS_URL)
                    return
                except Exception as exc2:
                    logging.warning("redis queue reconnect attempt failed: %s", exc2)
                    delay = min(delay * 1.5, 30.0)

        redis_reconnect_task = asyncio.create_task(_redis_reconnect_loop())
    # Warm model as soon as Ollama is up (first chat request avoids cold load)
    try:
        await ensure_single_model_loaded(settings.OLLAMA_MODEL)
        log_event("ollama_startup_warm", model=settings.OLLAMA_MODEL)
    except Exception as exc:
        logging.warning("ollama startup warm failed (keepalive will retry): %s", exc)
    # Also warm the Library worker model on the nanobot (over LAN) so it's
    # ready before the first research job arrives.  Non-fatal if nanobot is
    # unreachable — the worker-side preload is the primary guarantee.
    worker_base = settings.resolved_worker_ollama_base_url()
    if worker_base:
        try:
            await ensure_single_model_loaded_at_base(
                worker_base, settings.WORKER_OLLAMA_MODEL, settings.WORKER_OLLAMA_NUM_CTX,
            )
            log_event("worker_ollama_startup_warm", model=settings.WORKER_OLLAMA_MODEL)
        except Exception as exc:
            logging.warning("worker ollama startup warm failed (non-fatal): %s", exc)
    # Keep the Ollama model warm so first-token latency stays predictable
    keepalive_task = asyncio.create_task(_model_keepalive())
    # Periodically clean up expired/inactive sessions and their user data
    cleanup_task = asyncio.create_task(_session_cleanup())
    # Reconcile library tasks whose SSE subscriber was closed before the worker
    # published a terminal status — surfaces failures even without a live browser.
    reconcile_task = asyncio.create_task(_reconcile_library_tasks())
    yield
    keepalive_task.cancel()
    cleanup_task.cancel()
    reconcile_task.cancel()
    if redis_reconnect_task is not None:
        redis_reconnect_task.cancel()
    for task in (keepalive_task, cleanup_task, reconcile_task, redis_reconnect_task):
        if task is None:
            continue
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_ollama_http()
    try:
        from backend.library.queue import close_queue as _close_queue
        await _close_queue()
    except Exception:
        pass


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
    from backend.routes import auth, chat, documents, index, admin, library
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    app.include_router(index.router, prefix="/api/index", tags=["index"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(library.router, prefix="/api/library", tags=["library"])

    # Resolve git HEAD once at app creation so /api/health is cheap.
    _startup_probe = _frontend_dist_probe(include_git=True)
    _startup_git_head = _startup_probe.get("git_head_short")

    @app.get("/api/health")
    async def health():
        """Include SPA bundle hint + git HEAD so you can verify the running process sees a fresh ``frontend/dist``."""
        out: dict = {
            "status": "ok",
            "service": "chunkylink",
            "git_head_short": _startup_git_head,
        }
        dist_index = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
        if dist_index.is_file():
            m = dist_index.stat().st_mtime
            probe = _frontend_dist_probe(include_git=False)
            out["frontend"] = {
                "index_html_mtime_unix": int(m),
                "index_html_built_at": datetime.fromtimestamp(m, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "dist_main_js": probe.get("dist_main_js"),
            }
        return out

    # Public site audio / assets under DATA_DIR (not in git); must register before SPA catch-all.
    media_root = settings.UPLOADS_DIR / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/uploads/media",
        StaticFiles(directory=str(media_root)),
        name="uploads_media",
    )

    # Serve the pre-built React frontend if the dist/ folder exists.
    # This lets uvicorn run as a single process without a separate nginx.
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        def serve_index() -> FileResponse:
            return FileResponse(
                str(dist / "index.html"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "CDN-Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa_root():
            return serve_index()

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Serve real files that exist (favicon, robots.txt, etc.)
            candidate = dist / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # Everything else → index.html (SPA client-side routing)
            return serve_index()

    return app


app = create_app()
