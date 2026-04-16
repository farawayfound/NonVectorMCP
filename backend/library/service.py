# -*- coding: utf-8 -*-
"""Library service — business logic for distributed research tasks."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import get_settings
from backend.database import get_db
from backend.library.models import OUTPUT_FORMATS, ResearchJob, StatusUpdate, TaskStatus, new_job_id
from backend.services.notify_email import parse_submitted_notify_email, resolve_notification_email
from backend.library.queue import get_queue
from backend.storage import get_user_upload_dir, get_user_index_dir

log = logging.getLogger(__name__)

MAX_CONCURRENT_ACTIVE_TASKS = 2
_ACTIVE_STATUSES = (TaskStatus.QUEUED, TaskStatus.CRAWLING, TaskStatus.SYNTHESIZING)
CANCELLED_RETENTION_MINUTES = 5

MIN_TARGET_TOKENS = 300
MAX_TARGET_TOKENS = 8000


def default_target_tokens(max_sources: int) -> int:
    return 300 + max_sources * 100


def _artifacts_dir(user_id: str) -> Path:
    d = get_settings().LIBRARY_ARTIFACTS_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

async def count_active_research_tasks(user_id: str) -> int:
    """Tasks that are queued or currently running on the worker (not yet in review)."""
    db = await get_db()
    try:
        ph = ",".join("?" * len(_ACTIVE_STATUSES))
        cursor = await db.execute(
            f"SELECT COUNT(*) AS c FROM library_tasks WHERE user_id = ? AND status IN ({ph})",
            (user_id, *_ACTIVE_STATUSES),
        )
        row = await cursor.fetchone()
        return int(dict(row)["c"])
    finally:
        await db.close()


async def count_total_research_tasks(user_id: str) -> int:
    """All tasks belonging to this user (any status)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) AS c FROM library_tasks WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return int(dict(row)["c"])
    finally:
        await db.close()


async def submit_research(
    user_id: str,
    prompt: str,
    max_sources: int = 10,
    focus_keywords: list[str] | None = None,
    notify_email: str | None = None,
    target_tokens: int | None = None,
    output_format: str | None = None,
) -> dict:
    """Validate, persist a library_tasks row, and enqueue the job."""
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > 2000:
        raise ValueError("prompt must be <=2000 characters")

    settings = get_settings()
    max_allowed_sources = settings.MAX_LIBRARY_SOURCES
    if max_sources < 1 or max_sources > max_allowed_sources:
        raise ValueError(f"max_sources must be between 1 and {max_allowed_sources}")

    if target_tokens is None:
        target_tokens = default_target_tokens(max_sources)
    if target_tokens < MIN_TARGET_TOKENS or target_tokens > MAX_TARGET_TOKENS:
        raise ValueError(
            f"target_tokens must be between {MIN_TARGET_TOKENS} and {MAX_TARGET_TOKENS}"
        )

    fmt = (output_format or "default").strip().lower()
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of: {', '.join(OUTPUT_FORMATS)}")

    total = await count_total_research_tasks(user_id)
    if total >= settings.MAX_LIBRARY_ARTICLES:
        raise ValueError(
            f"you have reached the maximum of {settings.MAX_LIBRARY_ARTICLES} research articles; "
            "delete some before submitting a new one"
        )

    active = await count_active_research_tasks(user_id)
    if active >= MAX_CONCURRENT_ACTIVE_TASKS:
        raise ValueError(
            f"at most {MAX_CONCURRENT_ACTIVE_TASKS} research tasks can be queued or running at a time; "
            "cancel one or wait for a task to finish"
        )

    notify_stored = parse_submitted_notify_email(notify_email)

    queue = get_queue()

    job_id = new_job_id()
    now = _now_iso()

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO library_tasks (id, user_id, prompt, status, created_at, updated_at, notify_email)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, user_id, prompt, TaskStatus.QUEUED, now, now, notify_stored),
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
        target_tokens=target_tokens,
        output_format=fmt,
    )
    await queue.enqueue(job)

    log.info("submitted research job %s for user %s", job_id, user_id)
    return {"job_id": job_id, "status": TaskStatus.QUEUED}


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

async def prune_stale_cancelled_tasks() -> None:
    """Remove cancelled rows older than CANCELLED_RETENTION_MINUTES (library list hygiene)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CANCELLED_RETENTION_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM library_tasks WHERE status = ? AND updated_at < ?",
            (TaskStatus.CANCELLED, cutoff),
        )
        await db.commit()
    finally:
        await db.close()


async def get_tasks(user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    await prune_stale_cancelled_tasks()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM library_tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        rows = await cursor.fetchall()
        out: list[dict] = []
        for r in rows:
            out.append(await ensure_failed_task_error(dict(r)))
        return out
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
        if not row:
            return None
        return await ensure_failed_task_error(dict(row))
    finally:
        await db.close()


async def get_task_by_id(task_id: str) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM library_tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return await ensure_failed_task_error(dict(row))
    finally:
        await db.close()


async def list_all_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    await prune_stale_cancelled_tasks()
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT t.id, t.user_id, t.prompt, t.status, t.created_at, t.updated_at,
                   t.completed_at, t.sources_found, t.artifact_path, t.error,
                   u.display_name AS user_display_name,
                   u.github_username AS user_github_username
            FROM library_tasks t
            LEFT JOIN users u ON t.user_id = u.id
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
        out: list[dict] = []
        for r in rows:
            d = await ensure_failed_task_error(dict(r))
            out.append({
                "id": d["id"],
                "user_id": d["user_id"],
                "prompt": d["prompt"],
                "status": d["status"],
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
                "completed_at": d["completed_at"],
                "sources_found": d["sources_found"],
                "artifact_path": d["artifact_path"],
                "error": d["error"],
                "user": {
                    "display_name": d.get("user_display_name"),
                    "github_username": d.get("user_github_username"),
                },
            })
        return out
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

    if task["status"] == TaskStatus.CANCELLED:
        raise ValueError("job was cancelled; refusing ingest")

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

    to_email = (task.get("notify_email") or "").strip().lower()
    if not to_email:
        to_email = await resolve_notification_email(user_id, None)
    if to_email:
        from backend.services.email import send_library_research_ready_email_sync

        prompt_text = task.get("prompt") or ""
        try:
            await asyncio.to_thread(
                send_library_research_ready_email_sync,
                to_email,
                prompt_text,
                job_id,
            )
        except Exception:
            log.warning(
                "library completion email failed for job %s (to=%s)",
                job_id,
                to_email,
                exc_info=True,
            )

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


def _ensure_cancellable(task: dict) -> None:
    if task["status"] in (TaskStatus.APPROVED, TaskStatus.REJECTED):
        raise ValueError("cannot cancel a finalised task")


async def _mark_task_cancelled(task_id: str) -> None:
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


async def _purge_and_publish_cancelled(task_id: str) -> None:
    try:
        q = get_queue()
    except RuntimeError:
        return
    await q.set_cancel_requested(task_id)
    await q.purge_job(task_id)
    await q.publish_status(
        StatusUpdate(job_id=task_id, status=TaskStatus.CANCELLED, message="Cancelled"),
    )


def _schedule_queue_after_cancel(task_id: str) -> None:
    """Purge Redis stream / PEL and publish cancel without blocking the HTTP response."""

    async def runner() -> None:
        try:
            await asyncio.wait_for(_purge_and_publish_cancelled(task_id), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("queue cancel timed out for job %s", task_id)
        except Exception:
            log.warning("queue cancel side-effects failed for job %s", task_id, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(runner())
    except RuntimeError:
        pass


async def cancel_task(user_id: str, task_id: str) -> dict:
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")
    _ensure_cancellable(task)
    await _mark_task_cancelled(task_id)
    _schedule_queue_after_cancel(task_id)
    log.info("cancelled task %s", task_id)
    return {"status": "cancelled"}


async def cancel_task_by_id(task_id: str) -> dict:
    task = await get_task_by_id(task_id)
    if not task:
        raise ValueError("task not found")
    _ensure_cancellable(task)
    await _mark_task_cancelled(task_id)
    _schedule_queue_after_cancel(task_id)
    log.info("cancelled task %s (by id)", task_id)
    return {"status": "cancelled"}


async def delete_task(user_id: str, task_id: str) -> dict:
    task = await get_task(user_id, task_id)
    if not task:
        raise ValueError("task not found")

    if task["status"] in _ACTIVE_STATUSES:
        _schedule_queue_after_cancel(task_id)

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
# Worker-reported failure (persists error even if no browser SSE is connected)
# ---------------------------------------------------------------------------

async def record_worker_task_failure(job_id: str, message: str) -> dict:
    """Set task to failed with error text when the nanobot worker POSTs /worker-failure."""
    err = ((message or "").strip() or "(no message)")[:8000]
    now = _now_iso()
    # Do not overwrite a finished review/import/cancel row if a stale worker POST arrives.
    terminal_ok = (
        TaskStatus.QUEUED,
        TaskStatus.CRAWLING,
        TaskStatus.SYNTHESIZING,
        TaskStatus.FAILED,
    )
    ph = ",".join("?" * len(terminal_ok))
    db = await get_db()
    try:
        cur = await db.execute(
            f"UPDATE library_tasks SET status = ?, error = ?, updated_at = ?, completed_at = ? "
            f"WHERE id = ? AND status IN ({ph})",
            (TaskStatus.FAILED, err, now, now, job_id, *terminal_ok),
        )
        await db.commit()
        if cur.rowcount == 0:
            log.warning("record_worker_task_failure: no row updated for job_id=%s", job_id)
            return {"ok": False, "reason": "not_found"}
    finally:
        await db.close()

    log.info("recorded worker failure for job %s (%d chars)", job_id, len(err))
    return {"ok": True}


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
    if status in (TaskStatus.REVIEW, TaskStatus.FAILED, TaskStatus.CANCELLED):
        sets.append("completed_at = ?")
        params.append(now)

    params.append(job_id)
    db = await get_db()
    try:
        await db.execute(f"UPDATE library_tasks SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()


def _is_failed_status(status: object) -> bool:
    return str(status or "").strip().lower() == "failed"


async def reconcile_active_tasks() -> None:
    """Sync terminal Redis status to DB for tasks whose SSE subscriber was not connected.

    Called from a background loop every ~30 s.  For every task currently in an
    active state (queued / crawling / synthesizing) it checks the Redis status
    stream.  If the worker already published a terminal event (failed / review /
    cancelled) that the backend never received (because no browser was watching
    the SSE feed), the DB row is updated so the UI reflects the real outcome.
    """
    db = await get_db()
    try:
        ph = ",".join("?" * len(_ACTIVE_STATUSES))
        cursor = await db.execute(
            f"SELECT id FROM library_tasks WHERE status IN ({ph})",
            _ACTIVE_STATUSES,
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    if not rows:
        return

    try:
        q = get_queue()
    except RuntimeError:
        return  # Redis not yet connected

    for row in rows:
        task_id = dict(row)["id"]
        try:
            # Priority: check for a "failed" entry anywhere in the stream.
            getter = getattr(q, "get_last_failed_status", None)
            latest_failed = await getter(task_id) if callable(getter) else None
            if latest_failed:
                msg = (latest_failed.message or "").strip()
                error_text = (
                    msg or
                    "Worker reported failure — check nanobot docker logs for details."
                )[:8000]
                await sync_task_status(task_id, TaskStatus.FAILED, error=error_text)
                log.info(
                    "reconciled task %s → failed (msg=%r)", task_id, error_text[:120],
                )
                continue

            # Also promote to "review" if the worker successfully delivered but the
            # SSE subscriber was gone before it published the "review" event.
            latest = await q.get_latest_status(task_id)
            if latest and latest.status == TaskStatus.REVIEW:
                await sync_task_status(task_id, TaskStatus.REVIEW)
                log.info("reconciled task %s → review", task_id)

        except Exception as exc:
            log.debug("reconcile: error checking task %s: %s", task_id, exc)


async def ensure_failed_task_error(task: dict) -> dict:
    """If status is failed but SQLite has no error text, backfill from Redis status stream."""
    if not _is_failed_status(task.get("status")):
        return task
    if (task.get("error") or "").strip():
        return task
    try:
        q = get_queue()
    except RuntimeError:
        return task
    try:
        getter = getattr(q, "get_last_failed_status", None)
        latest = await getter(task["id"]) if callable(getter) else None
        if latest is None:
            lu = await q.get_latest_status(task["id"])
            if lu is not None and _is_failed_status(lu.status):
                latest = lu
    except Exception:
        log.debug("ensure_failed_task_error: redis read failed for %s", task.get("id"), exc_info=True)
        return task
    if latest is None:
        return task
    msg = (latest.message or "").strip()
    if not msg:
        return task
    await sync_task_status(
        task["id"],
        TaskStatus.FAILED,
        error=msg[:8000],
        sources_found=int(task.get("sources_found") or 0),
    )
    merged = dict(task)
    merged["error"] = msg[:8000]
    return merged
