# -*- coding: utf-8 -*-
"""Admin routes — invite codes, activity log, system stats, demo KB management."""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse

from backend.auth.middleware import require_admin
from backend.auth.invite_codes import create_invite
from backend.database import get_db
from backend.chat.ollama_client import (
    health_check, list_models, pull_model, delete_model,
    list_loaded_models, ensure_single_model_loaded,
    get_model_context_window, get_inference_stats,
)
from backend.config import get_settings
from backend.storage import get_demo_upload_dir, get_demo_index_dir
from backend.logger import log_event

router = APIRouter()

# Track demo indexing job state
_demo_job: dict = {"status": "idle", "error": None}

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".pptx", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _run_demo_index():
    """Run demo KB indexing in background thread."""
    global _demo_job
    try:
        _demo_job = {"status": "running", "error": None}
        from backend.indexers.build_index import main as build_main
        src = str(get_demo_upload_dir())
        out = str(get_demo_index_dir())
        build_main(src_dir=src, out_dir=out)
        _demo_job = {"status": "complete", "error": None}
        log_event("demo_index_complete")
    except Exception as e:
        logging.exception("Demo KB indexing failed")
        _demo_job = {"status": "failed", "error": str(e)}
        log_event("demo_index_failed", error=str(e))


@router.get("/stats")
async def admin_stats(request: Request, user: dict = Depends(require_admin)):
    """System-wide statistics for the admin dashboard."""
    db = await get_db()
    try:
        users_row = await (await db.execute("SELECT COUNT(*) as c FROM users")).fetchone()
        codes_row = await (await db.execute("SELECT COUNT(*) as c FROM invite_codes WHERE active = 1")).fetchone()
        sessions_row = await (await db.execute("SELECT COUNT(*) as c FROM sessions")).fetchone()
        activity_row = await (await db.execute(
            "SELECT COUNT(*) as c FROM activity_log WHERE timestamp > datetime('now', '-24 hours')"
        )).fetchone()

        return {
            "users": dict(users_row)["c"],
            "active_invite_codes": dict(codes_row)["c"],
            "active_sessions": dict(sessions_row)["c"],
            "activity_last_24h": dict(activity_row)["c"],
        }
    finally:
        await db.close()


@router.get("/users")
async def admin_users(request: Request, user: dict = Depends(require_admin)):
    """List all users."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, github_username, display_name, role, created_at, last_seen FROM users ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return {"users": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.get("/invite-codes")
async def list_invite_codes(request: Request, user: dict = Depends(require_admin)):
    """List all invite codes."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM invite_codes ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return {"codes": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.post("/invite-codes")
async def create_invite_code(request: Request, user: dict = Depends(require_admin)):
    """Create a new invite code.

    Body: {"label": "...", "max_uses": 0, "expires_at": null}
    """
    body = await request.json()
    label = body.get("label", "")
    max_uses = body.get("max_uses", 0)
    expires_at = body.get("expires_at")

    db = await get_db()
    try:
        code = await create_invite(
            db, created_by=user["user_id"], label=label,
            max_uses=max_uses, expires_at=expires_at,
        )
        log_event("invite_created", user_id=user["user_id"], code=code, label=label)
        return {"code": code, "label": label, "max_uses": max_uses, "expires_at": expires_at}
    finally:
        await db.close()


@router.delete("/invite-codes/{code}")
async def deactivate_invite_code(
    code: str, request: Request, user: dict = Depends(require_admin)
):
    """Deactivate an invite code."""
    db = await get_db()
    try:
        result = await db.execute(
            "UPDATE invite_codes SET active = 0 WHERE code = ?", (code,)
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Invite code not found")
        log_event("invite_deactivated", user_id=user["user_id"], code=code)
        return {"status": "deactivated", "code": code}
    finally:
        await db.close()


@router.get("/activity")
async def admin_activity(
    request: Request,
    user: dict = Depends(require_admin),
    limit: int = 100,
    offset: int = 0,
    event: str | None = None,
    user_id: str | None = None,
):
    """Query the activity log."""
    db = await get_db()
    try:
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        if event:
            query += " AND event = ?"
            params.append(event)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        count_cursor = await db.execute("SELECT COUNT(*) as c FROM activity_log")
        total = dict(await count_cursor.fetchone())["c"]

        return {"activity": [dict(r) for r in rows], "total": total}
    finally:
        await db.close()


@router.get("/ollama")
async def admin_ollama(request: Request, user: dict = Depends(require_admin)):
    """Check Ollama status, available models, memory state, and inference metrics."""
    status = await health_check()
    models = await list_models()
    loaded = await list_loaded_models()
    settings = get_settings()
    loaded_names = [m.get("name", "") for m in loaded]
    context_window = await get_model_context_window(settings.OLLAMA_MODEL)
    return {
        "ollama": status,
        "configured_model": settings.OLLAMA_MODEL,
        "models": models,
        "loaded_models": loaded,
        "loaded_names": loaded_names,
        "context_window": context_window,
        "inference_stats": get_inference_stats(),
    }


@router.put("/ollama/model")
async def admin_ollama_set_model(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    """Set the active Ollama model for inference and immediately begin preloading it."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")
    settings = get_settings()
    settings.OLLAMA_MODEL = name
    log_event("ollama_model_changed", user_id=user["user_id"], model=name)
    background_tasks.add_task(ensure_single_model_loaded, name)
    return {"status": "ok", "model": name, "preloading": True}


@router.post("/ollama/pull")
async def admin_ollama_pull(request: Request, user: dict = Depends(require_admin)):
    """Pull a model from the Ollama registry (streams progress)."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")

    log_event("ollama_pull_start", user_id=user["user_id"], model=name)

    async def event_stream():
        try:
            async for progress in pull_model(name):
                yield f"data: {json.dumps(progress)}\n\n"
            log_event("ollama_pull_complete", user_id=user["user_id"], model=name)
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
            log_event("ollama_pull_failed", user_id=user["user_id"], model=name, error=str(e))
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/ollama/delete")
async def admin_ollama_delete_model(request: Request, user: dict = Depends(require_admin)):
    """Delete a model from Ollama."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")
    try:
        result = await delete_model(name)
        log_event("ollama_model_deleted", user_id=user["user_id"], model=name)
        return result
    except Exception as e:
        raise HTTPException(500, f"Failed to delete model: {e}")


# ── Demo KB Management ────────────────────────────────────────────────────────

@router.get("/demo/documents")
async def demo_list_documents(request: Request, user: dict = Depends(require_admin)):
    """List all documents in the demo knowledge base upload directory."""
    upload_dir = get_demo_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for f in sorted(upload_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            stat = f.stat()
            docs.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "suffix": f.suffix.lower(),
            })
    return {"documents": docs, "count": len(docs)}


@router.post("/demo/upload")
async def demo_upload_document(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
):
    """Upload a document to the demo knowledge base."""
    if not file.filename:
        raise HTTPException(400, "Filename is required")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large. Maximum: {MAX_FILE_SIZE // (1024*1024)} MB")

    upload_dir = get_demo_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = upload_dir / safe_name
    dest.write_bytes(content)

    log_event("demo_upload", user_id=user["user_id"], filename=safe_name, size=len(content))
    return {"status": "uploaded", "filename": safe_name, "size_bytes": len(content)}


@router.delete("/demo/documents/{filename}")
async def demo_delete_document(
    filename: str,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Delete a document from the demo knowledge base."""
    upload_dir = get_demo_upload_dir()
    target = upload_dir / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Document not found")
    target.unlink()
    log_event("demo_delete", user_id=user["user_id"], filename=filename)
    return {"status": "deleted", "filename": filename}


@router.post("/demo/build")
async def demo_build_index(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    """Trigger indexing of the demo knowledge base documents."""
    global _demo_job
    if _demo_job.get("status") == "running":
        return {"status": "already_running"}

    upload_dir = get_demo_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for ext in ALLOWED_EXTENSIONS:
        files.extend(upload_dir.glob(f"*{ext}"))
    if not files:
        raise HTTPException(400, "No documents in demo KB. Upload files first.")

    log_event("demo_index_start", user_id=user["user_id"], file_count=len(files))
    background_tasks.add_task(_run_demo_index)
    _demo_job = {"status": "running", "error": None}
    return {"status": "started", "files": len(files)}


@router.get("/demo/status")
async def demo_index_status(request: Request, user: dict = Depends(require_admin)):
    """Get the current status of the demo KB indexing job."""
    index_dir = get_demo_index_dir()
    detail_dir = index_dir / "detail"

    chunk_count = 0
    categories: dict[str, int] = {}
    if detail_dir.exists():
        for f in detail_dir.glob("chunks.*.jsonl"):
            if f.name == "chunks.jsonl":
                continue
            cat = f.stem.replace("chunks.", "")
            count = sum(1 for line in open(f, encoding="utf-8") if line.strip())
            categories[cat] = count
            chunk_count += count

    return {
        "job": _demo_job,
        "total_chunks": chunk_count,
        "categories": categories,
    }
