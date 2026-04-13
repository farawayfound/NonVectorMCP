# -*- coding: utf-8 -*-
"""Library service — business logic for distributed research tasks."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_settings
from backend.database import get_db
from backend.library.models import ResearchJob, TaskStatus, new_job_id
from backend.library.queue import get_queue
from backend.storage import get_user_upload_dir, get_user_index_dir

log = logging.getLogger(__name__)


def _artifacts_dir(user_id: str) -> Path:
    d = get_settings().LIBRARY_ARTIFACTS_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

async def submit_research(
    user_id: str,
    prompt: str,
    max_sources: int = 10,
    focus_keywords: list[str] | None = None,
) -> dict:
    """Validate, persist a library_tasks row, and enqueue the job."""
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > 2000:
        raise ValueError("prompt must be <=2000 characters")

    job_id = new_job_id()
    now = _now_iso()

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO library_tasks (id, user_id, prompt, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, user_id, prompt, TaskStatus.QUEUED, now, now),
        )
        await db.commit()
    finally:
        await db.close()

    job = ResearchJob(
        job_id=job_id,
        user_id=user_id,
        prompt=prompt,
        max_sources=max_sources,
        focus_keywords=focus_keywords or [],
        created_at=now,
    )
    await get_queue().enqueue(job)

    log.info("submitted research job %s for user %s", job_id, user_id)
    return {"job_id": job_id, "status": TaskStatus.QUEUED}


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

async def get_tasks(user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM library_tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_task(user_id: str, task_id: str) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM library_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_task_artifact(user_id: str, task_id: str) -> str | None:
    """Return the Markdown content of a completed research artifact."""
    task = await get_task(user_id, task_id)
    if not task or not task.get("artifact_path"):
        return None
    path = Path(task["artifact_path"])
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# ---------------------------------------------------------------------------
# Receive result (called by nanobot worker)
# ---------------------------------------------------------------------------

async def receive_result(
    job_id: str,
    markdown: str,
    sources: list[dict],
    summary: str = "",
) -> dict:
    """Store the worker's artifact and move task to 'review'."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM library_tasks WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"unknown job_id {job_id}")
        task = dict(row)
    finally:
        await db.close()

    user_id = task["user_id"]
    artifacts = _artifacts_dir(user_id)
    artifact_path = artifacts / f"{job_id}.md"
    artifact_path.write_text(markdown, encoding="utf-8")

    meta_path = artifacts / f"{job_id}.meta.json"
    meta_path.write_text(json.dumps({
        "sources": sources,
        "summary": summary,
    }, indent=2), encoding="utf-8")

    now = _now_iso()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE library_tasks SET status = ?, updated_at = ?, completed_at = ?,"
            " sources_found = ?, artifact_path = ? WHERE id = ?",
            (TaskStatus.REVIEW, now, now, len(sources), str(artifact_path), job_id),
        )
        await db.commit()
    finally:
        await db.close()

    log.info("received result for job %s — %d sources, moved to review", job_id, len(sources))
    return {"status": "review", "artifact_path": str(artifact_path)}


# ---------------------------------------------------------------------------
# Approve — runs quality gate + dedup, writes to user uploads, triggers index
# ---------------------------------------------------------------------------

async def approve_task(user_id: str, task_id: str) -> dict:
    """Quality-gate the artifact, save it as an uploaded doc, and trigger indexing."""
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")
    if task["status"] != TaskStatus.REVIEW:
        raise ValueError(f"task is in '{task['status']}' state, expected 'review'")

    artifact_path = Path(task["artifact_path"])
    if not artifact_path.exists():
        raise ValueError("artifact file missing")

    markdown = artifact_path.read_text(encoding="utf-8")

    from backend.learn.learn_engine import gate_quality
    ok, reason = gate_quality(markdown)
    if not ok:
        return {"status": "rejected_quality", "reason": reason}

    from backend.learn.learn_engine import LearnEngine
    index_dir = get_user_index_dir(user_id)
    engine = LearnEngine(index_dir)
    result = engine.process(
        text=markdown,
        topic_key="library-research",
        category="auto",
        tags=["library", "research"],
        title=task["prompt"][:60],
        user_id=user_id,
    )

    if result["status"] == "duplicate":
        now = _now_iso()
        db = await get_db()
        try:
            await db.execute(
                "UPDATE library_tasks SET status = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.REJECTED, now, task_id),
            )
            await db.commit()
        finally:
            await db.close()
        return {
            "status": "duplicate",
            "existing_chunk_id": result.get("existing_chunk_id"),
            "similarity": result.get("similarity"),
        }

    safe_name = f"library_{task_id}.md"
    upload_dir = get_user_upload_dir(user_id)
    dest = upload_dir / safe_name
    dest.write_text(markdown, encoding="utf-8")

    now = _now_iso()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE library_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.APPROVED, now, task_id),
        )
        await db.commit()
    finally:
        await db.close()

    log.info("approved task %s — saved as %s", task_id, safe_name)
    return {
        "status": "approved",
        "filename": safe_name,
        "learn_result": result,
    }


# ---------------------------------------------------------------------------
# Reject / cancel
# ---------------------------------------------------------------------------

async def reject_task(user_id: str, task_id: str) -> dict:
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")

    now = _now_iso()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE library_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.REJECTED, now, task_id),
        )
        await db.commit()
    finally:
        await db.close()

    log.info("rejected task %s", task_id)
    return {"status": "rejected"}


async def cancel_task(user_id: str, task_id: str) -> dict:
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")
    if task["status"] in (TaskStatus.APPROVED, TaskStatus.REJECTED):
        raise ValueError("cannot cancel a finalised task")

    now = _now_iso()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE library_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.CANCELLED, now, task_id),
        )
        await db.commit()
    finally:
        await db.close()

    log.info("cancelled task %s", task_id)
    return {"status": "cancelled"}


async def delete_task(user_id: str, task_id: str) -> dict:
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")

    if task.get("artifact_path"):
        p = Path(task["artifact_path"])
        if p.exists():
            p.unlink(missing_ok=True)
        meta = p.with_suffix(".meta.json")
        if meta.exists():
            meta.unlink(missing_ok=True)

    db = await get_db()
    try:
        await db.execute("DELETE FROM library_tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        await db.commit()
    finally:
        await db.close()

    log.info("deleted task %s", task_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Update status (used by the status-sync background task)
# ---------------------------------------------------------------------------

async def sync_task_status(job_id: str, status: str, **extra) -> None:
    """Update a task's status from a queue status event."""
    now = _now_iso()
    sets = ["status = ?", "updated_at = ?"]
    params: list = [status, now]

    if "sources_found" in extra:
        sets.append("sources_found = ?")
        params.append(extra["sources_found"])
    if "error" in extra:
        sets.append("error = ?")
        params.append(extra["error"])
    if status in (TaskStatus.REVIEW, TaskStatus.FAILED):
        sets.append("completed_at = ?")
        params.append(now)

    params.append(job_id)
    db = await get_db()
    try:
        await db.execute(f"UPDATE library_tasks SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()
