# -*- coding: utf-8 -*-
"""Index management routes — build, status, stats."""
import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks

from backend.auth.middleware import require_auth
from backend.storage import get_user_upload_dir, get_user_index_dir, get_user_chunking_config
from backend.logger import log_event

router = APIRouter()

# Track background indexing jobs per user
_active_jobs: dict[str, dict] = {}


def _read_manifest_totals(out_dir: str) -> tuple[int, int]:
    """Return (file_count, chunk_count) from the run manifest, best-effort."""
    try:
        manifest = Path(out_dir) / "manifests" / "run_manifest.json"
        if manifest.exists():
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
                totals = data.get("totals", {}) or {}
                return int(totals.get("files", 0)), int(totals.get("chunks", 0))
    except Exception:
        pass
    return 0, 0


def _send_complete_email_sync(
    to_email: str,
    doc_count: int,
    chunk_count: int,
    insights_generated: bool,
    failed: bool = False,
    error: str | None = None,
) -> None:
    """Fire the completion email from a sync background thread."""
    if not to_email:
        return
    try:
        from backend.services.email import send_index_complete_email
        try:
            asyncio.run(send_index_complete_email(
                to_email, doc_count, chunk_count, insights_generated,
                failed=failed, error=error,
            ))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(send_index_complete_email(
                    to_email, doc_count, chunk_count, insights_generated,
                    failed=failed, error=error,
                ))
            finally:
                loop.close()
    except Exception as exc:
        logging.warning("index-complete email send failed for %s: %s", to_email, exc)


def _run_index(
    user_id: str,
    src_dir: str,
    out_dir: str,
    config_overrides: dict | None = None,
    generate_insights: bool = True,
    notify_email: str | None = None,
):
    """Run indexing in background thread — always a clean rebuild for user indexes."""
    try:
        _active_jobs[user_id] = {"status": "running", "error": None}
        from backend.indexers.build_index import main as build_main
        build_main(src_dir=src_dir, out_dir=out_dir, config_overrides=config_overrides,
                   full_rebuild=True)

        if generate_insights:
            _active_jobs[user_id] = {"status": "building_insights", "error": None}
            try:
                from backend.services.insights_service import build_all_insights_sync
                build_all_insights_sync(user_id)
            except Exception as exc:
                logging.warning("insights generation failed for user %s: %s", user_id, exc)

        _active_jobs[user_id] = {"status": "complete", "error": None}
        log_event("index_complete", user_id=user_id, insights=generate_insights)

        doc_count, chunk_count = _read_manifest_totals(out_dir)
        _send_complete_email_sync(
            notify_email or "", doc_count, chunk_count, generate_insights,
        )
    except Exception as e:
        logging.exception(f"Indexing failed for user {user_id}")
        _active_jobs[user_id] = {"status": "failed", "error": str(e)}
        log_event("index_failed", user_id=user_id, error=str(e))
        _send_complete_email_sync(
            notify_email or "", 0, 0, generate_insights, failed=True, error=str(e),
        )


import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _resolve_notify_email(user_id: str, submitted: str | None) -> str | None:
    """Decide which email (if any) to notify on completion.

    Priority: submitted (validated) → users.email → access_requests.email lookup.
    If submitted is provided, also persist it to users.email for future runs.
    """
    from backend.database import get_db

    cleaned = (submitted or "").strip().lower()
    if cleaned and not _EMAIL_RE.match(cleaned):
        raise HTTPException(400, "Invalid email address")

    db = await get_db()
    try:
        if cleaned:
            await db.execute("UPDATE users SET email = ? WHERE id = ?", (cleaned, user_id))
            await db.commit()
            return cleaned

        cursor = await db.execute("SELECT email FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if row and row["email"]:
            return row["email"]

        cursor = await db.execute(
            "SELECT ar.email FROM access_requests ar "
            "JOIN sessions s ON s.user_id = ? "
            "JOIN invite_codes ic ON ic.code = ar.invite_code "
            "WHERE ar.status = 'sent' AND ic.created_by = 'system:request-access' "
            "ORDER BY ar.created_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row and row["email"]:
            await db.execute("UPDATE users SET email = ? WHERE id = ?", (row["email"], user_id))
            await db.commit()
            return row["email"]
    finally:
        await db.close()

    return None


@router.post("/build")
async def build_index(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth),
):
    """Trigger indexing of the user's uploaded documents."""
    user_id = user["user_id"]

    # Check if already running
    job = _active_jobs.get(user_id)
    if job and job["status"] in ("running", "building_insights"):
        return {"status": "already_running"}

    try:
        body = await request.json()
    except Exception:
        body = {}
    generate_insights = bool(body.get("generate_insights", True))
    submitted_email = body.get("notify_email")

    notify_email = await _resolve_notify_email(user_id, submitted_email)

    src_dir = str(get_user_upload_dir(user_id))
    out_dir = str(get_user_index_dir(user_id))

    # Check there are files to index
    src = Path(src_dir)
    files = list(src.glob("**/*.pdf")) + list(src.glob("**/*.txt")) + \
            list(src.glob("**/*.docx")) + list(src.glob("**/*.pptx")) + \
            list(src.glob("**/*.csv"))
    if not files:
        raise HTTPException(400, "No documents to index. Upload files first.")

    user_config = get_user_chunking_config(user_id)
    config_overrides = {
        "PARA_TARGET_TOKENS": user_config["chunk_size"],
        "PARA_OVERLAP_TOKENS": user_config["chunk_overlap"],
        "ENABLE_AUTO_TAGGING": user_config["enable_nlp_tagging"],
    }

    log_event(
        "index_start", user_id=user_id, file_count=len(files),
        insights=generate_insights, notify=bool(notify_email),
    )
    background_tasks.add_task(
        _run_index, user_id, src_dir, out_dir, config_overrides,
        generate_insights, notify_email,
    )
    _active_jobs[user_id] = {"status": "running", "error": None}

    return {
        "status": "started",
        "files": len(files),
        "generate_insights": generate_insights,
        "notify_email": notify_email,
        "has_email": bool(notify_email),
    }


@router.get("/email-status")
async def index_email_status(request: Request, user: dict = Depends(require_auth)):
    """Tell the frontend whether the user already has an email on file."""
    user_id = user["user_id"]
    email = await _resolve_notify_email(user_id, None)
    return {"has_email": bool(email), "email": email or ""}


@router.get("/status")
async def index_status(request: Request, user: dict = Depends(require_auth)):
    """Check the status of the user's indexing job."""
    user_id = user["user_id"]
    job = _active_jobs.get(user_id)

    index_dir = get_user_index_dir(user_id)
    manifest = index_dir / "manifests" / "run_manifest.json"
    last_run = None
    if manifest.exists():
        try:
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
                last_run = {
                    "completed": data.get("completed"),
                    "chunks": data.get("totals", {}).get("chunks", 0),
                    "files": data.get("totals", {}).get("files", 0),
                }
        except Exception:
            pass

    return {
        "job": job or {"status": "idle", "error": None},
        "last_run": last_run,
    }


@router.get("/stats")
async def index_stats(request: Request, user: dict = Depends(require_auth)):
    """Get detailed index statistics."""
    user_id = user["user_id"]
    index_dir = get_user_index_dir(user_id)
    detail_dir = index_dir / "detail"

    stats = {"total_chunks": 0, "categories": {}, "has_index": False}

    if detail_dir.exists():
        for f in detail_dir.glob("chunks.*.jsonl"):
            if f.name == "chunks.jsonl":
                continue
            cat = f.stem.replace("chunks.", "")
            count = sum(1 for line in open(f, encoding="utf-8") if line.strip())
            stats["categories"][cat] = count
            stats["total_chunks"] += count
            stats["has_index"] = True

    # State info
    state_file = index_dir / "state" / "processing_state.json"
    if state_file.exists():
        try:
            with open(state_file, encoding="utf-8") as f:
                state = json.load(f)
                stats["last_run"] = state.get("last_run")
                stats["processed_files"] = len(state.get("processed_files", {}))
        except Exception:
            pass

    return stats
