# -*- coding: utf-8 -*-
"""Index management routes — build, status, stats."""
import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks

from backend.auth.middleware import require_auth
from backend.storage import get_user_upload_dir, get_user_index_dir
from backend.logger import log_event

router = APIRouter()

# Track background indexing jobs per user
_active_jobs: dict[str, dict] = {}


def _run_index(user_id: str, src_dir: str, out_dir: str):
    """Run indexing in background thread."""
    try:
        _active_jobs[user_id] = {"status": "running", "error": None}
        from backend.indexers.build_index import main as build_main
        build_main(src_dir=src_dir, out_dir=out_dir)
        _active_jobs[user_id] = {"status": "complete", "error": None}
        log_event("index_complete", user_id=user_id)
    except Exception as e:
        logging.exception(f"Indexing failed for user {user_id}")
        _active_jobs[user_id] = {"status": "failed", "error": str(e)}
        log_event("index_failed", user_id=user_id, error=str(e))


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
    if job and job["status"] == "running":
        return {"status": "already_running"}

    src_dir = str(get_user_upload_dir(user_id))
    out_dir = str(get_user_index_dir(user_id))

    # Check there are files to index
    src = Path(src_dir)
    files = list(src.glob("**/*.pdf")) + list(src.glob("**/*.txt")) + \
            list(src.glob("**/*.docx")) + list(src.glob("**/*.pptx")) + \
            list(src.glob("**/*.csv"))
    if not files:
        raise HTTPException(400, "No documents to index. Upload files first.")

    log_event("index_start", user_id=user_id, file_count=len(files))
    background_tasks.add_task(_run_index, user_id, src_dir, out_dir)
    _active_jobs[user_id] = {"status": "running", "error": None}

    return {"status": "started", "files": len(files)}


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
