# -*- coding: utf-8 -*-
"""Library research routes — submit, track, review, approve/reject."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.auth.middleware import require_auth
from backend.config import get_settings
from backend.library import service
from backend.library.queue import get_queue
from backend.logger import log_event

router = APIRouter()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Submit a new research task
# ---------------------------------------------------------------------------

@router.post("/research")
async def submit_research(request: Request, user: dict = Depends(require_auth)):
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    max_sources = int(body.get("max_sources", 10))
    focus_keywords = body.get("focus_keywords") or []
    notify_email = (body.get("notify_email") or "").strip() or None

    try:
        result = await service.submit_research(
            user_id=user["user_id"],
            prompt=prompt,
            max_sources=max_sources,
            focus_keywords=focus_keywords,
            notify_email=notify_email,
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    log_event("library_submit", user_id=user["user_id"], job_id=result["job_id"])
    return result


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------

@router.get("/tasks")
async def list_tasks(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    tasks = await service.get_tasks(user["user_id"], limit=limit, offset=offset)
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(require_auth)):
    task = await service.get_task(user["user_id"], task_id)
    if not task:
        raise HTTPException(404, "task not found")

    artifact = await service.get_task_artifact(user["user_id"], task_id)
    sources: list = []
    if task.get("artifact_path"):
        meta_path = Path(task["artifact_path"]).with_suffix(".meta.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                sources = meta.get("sources", [])
            except Exception:
                pass

    return {**task, "artifact": artifact, "sources": sources}


# ---------------------------------------------------------------------------
# SSE stream for real-time status updates
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/stream")
async def stream_task_status(task_id: str, user: dict = Depends(require_auth)):
    task = await service.get_task(user["user_id"], task_id)
    if not task:
        raise HTTPException(404, "task not found")

    queue = get_queue()

    async def event_generator():
        try:
            async for update in queue.subscribe_status(task_id):
                if update is None:
                    yield ": keepalive\n\n"
                    continue
                data = json.dumps(update.to_dict())
                yield f"data: {data}\n\n"

                await service.sync_task_status(
                    update.job_id,
                    update.status,
                    sources_found=update.sources_found,
                )

                if update.status in ("review", "failed", "cancelled"):
                    yield "data: [DONE]\n\n"
                    return
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Approve / reject / cancel / delete
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, user: dict = Depends(require_auth)):
    try:
        result = await service.approve_task(user["user_id"], task_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_event("library_approve", user_id=user["user_id"], task_id=task_id, result=result.get("status"))
    return result


@router.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str, user: dict = Depends(require_auth)):
    try:
        result = await service.reject_task(user["user_id"], task_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_event("library_reject", user_id=user["user_id"], task_id=task_id)
    return result


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, user: dict = Depends(require_auth)):
    try:
        result = await service.cancel_task(user["user_id"], task_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_event("library_cancel", user_id=user["user_id"], task_id=task_id)
    return result


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: dict = Depends(require_auth)):
    try:
        result = await service.delete_task(user["user_id"], task_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


# ---------------------------------------------------------------------------
# Internal ingest endpoint (called by nanobot worker)
# ---------------------------------------------------------------------------

@router.post("/ingest")
async def ingest_result(request: Request):
    """Receive a completed research artifact from the nanobot worker."""
    settings = get_settings()
    api_key = request.headers.get("X-Nanobot-Key", "")
    if not settings.NANOBOT_API_KEY or api_key != settings.NANOBOT_API_KEY:
        raise HTTPException(403, "invalid or missing nanobot API key")

    body = await request.json()
    job_id = body.get("job_id")
    markdown = body.get("markdown", "")
    sources = body.get("sources", [])
    summary = body.get("summary", "")

    if not job_id or not markdown:
        raise HTTPException(400, "job_id and markdown are required")

    try:
        result = await service.receive_result(job_id, markdown, sources, summary)
    except ValueError as e:
        raise HTTPException(404, str(e))

    log_event("library_ingest", job_id=job_id, sources=len(sources))
    return result
