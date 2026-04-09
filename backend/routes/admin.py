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
    preload_model, unload_model,
    get_model_context_window, get_inference_stats, get_readiness_metrics,
)
from backend.config import get_settings
from backend.storage import get_demo_upload_dir, get_demo_index_dir
from backend.logger import log_event

router = APIRouter()

# Track demo indexing job state
_demo_job: dict = {"status": "idle", "error": None}

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".pptx", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _inject_curated_chunks(index_dir: Path) -> int:
    """Write default Q&A/STAR items as searchable chunks in the index."""
    items = _read_qa()
    if not items:
        return 0

    detail_dir = index_dir / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    main_chunks = detail_dir / "chunks.jsonl"
    curated_chunks = detail_dir / "chunks.curated.jsonl"

    chunks = []
    for item in items:
        if item["type"] == "star":
            text = (
                f"Q: {item['question']}\n\n"
                f"Situation: {item.get('situation', '')}\n"
                f"Task: {item.get('task', '')}\n"
                f"Action: {item.get('action', '')}\n"
                f"Result: {item.get('result', '')}"
            )
        else:
            text = f"Q: {item['question']}\nA: {item.get('answer', '')}"

        chunk = {
            "id": f"curated::{item['id']}",
            "text": text,
            "metadata": {
                "nlp_category": "curated",
                "curated": True,
                "qa_type": item["type"],
                "source": "admin_default_qa",
            },
            "tags": ["curated", item["type"]],
            "related_chunks": [],
        }
        chunks.append(chunk)

    with open(curated_chunks, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    with open(main_chunks, "a", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    return len(chunks)


def _run_demo_index():
    """Run demo KB indexing in background thread with granular progress tracking."""
    global _demo_job
    try:
        # Phase 1: Index uploaded documents
        _demo_job = {"status": "running", "step": "indexing", "detail": "Building document index", "error": None}
        from backend.indexers.build_index import main as build_main
        src = str(get_demo_upload_dir())
        out = str(get_demo_index_dir())
        build_main(src_dir=src, out_dir=out)
        log_event("demo_index_complete")

        # Phase 2: Inject curated Q&A/STAR chunks
        _demo_job = {"status": "running", "step": "indexing", "detail": "Injecting curated Q&A chunks", "error": None}
        n_curated = _inject_curated_chunks(get_demo_index_dir())
        if n_curated:
            logging.info(f"Injected {n_curated} curated chunks into demo index")

        # Phase 3+4: Generate and validate suggested questions
        def _progress_cb(step: str, detail: str):
            global _demo_job
            _demo_job = {"status": "running", "step": step, "detail": detail, "error": None}

        try:
            import asyncio
            from backend.chat.suggestions import generate_and_save_suggestions
            _demo_job = {"status": "running", "step": "generating", "detail": "Generating suggested questions", "error": None}
            asyncio.run(generate_and_save_suggestions(get_demo_index_dir(), progress_cb=_progress_cb))
            log_event("demo_suggestions_generated")
        except Exception as e:
            logging.warning(f"Suggestion generation failed (non-fatal): {e}")

        # Phase 5: Merge curated questions into suggestions
        qa_items = _read_qa()
        if qa_items:
            curated_questions = [item["question"] for item in qa_items if item.get("question")]
            suggestions = _read_suggestions()
            existing = set(suggestions)
            for q in curated_questions:
                if q not in existing:
                    suggestions.insert(0, q)
            _write_suggestions(suggestions)

        _demo_job = {"status": "complete", "step": "complete", "detail": None, "error": None}
    except Exception as e:
        logging.exception("Demo KB indexing failed")
        _demo_job = {"status": "failed", "step": "failed", "detail": None, "error": str(e)}
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
        "suggestion_model": settings.SUGGESTION_MODEL,
        "models": models,
        "loaded_models": loaded,
        "loaded_names": loaded_names,
        "context_window": context_window,
        "inference_stats": get_inference_stats(),
        "readiness": get_readiness_metrics(),
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


@router.post("/ollama/load")
async def admin_ollama_load_model(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    """Load a model into Ollama memory (unloads all others first)."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")
    settings = get_settings()
    settings.OLLAMA_MODEL = name
    log_event("ollama_model_loaded", user_id=user["user_id"], model=name)
    background_tasks.add_task(ensure_single_model_loaded, name)
    return {"status": "loading", "name": name}


@router.post("/ollama/unload")
async def admin_ollama_unload_model(
    request: Request, user: dict = Depends(require_admin),
):
    """Unload a model from Ollama memory."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")
    try:
        await unload_model(name)
        log_event("ollama_model_unloaded", user_id=user["user_id"], model=name)
        return {"status": "unloaded", "name": name}
    except Exception as e:
        raise HTTPException(500, f"Failed to unload model: {e}")


@router.put("/ollama/suggestion-model")
async def admin_set_suggestion_model(
    request: Request, user: dict = Depends(require_admin),
):
    """Set which Ollama model is used for generating suggested questions during index build."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Model name is required")
    settings = get_settings()
    settings.SUGGESTION_MODEL = name
    settings.save_admin_config()
    log_event("suggestion_model_changed", user_id=user["user_id"], model=name)
    return {"status": "ok", "suggestion_model": name}


# ── Chat Performance Log ─────────────────────────────────────────────────────

_PERF_PAGE_SIZE = 20
_PERF_ROLLING_WINDOW = 100


@router.get("/perf")
async def admin_perf_log(
    request: Request,
    user: dict = Depends(require_admin),
    page: int = 1,
    page_size: int = _PERF_PAGE_SIZE,
):
    """Paginated chat performance log — rolling window of the latest 100 prompts."""
    page = max(1, page)
    page_size = max(1, min(page_size, _PERF_PAGE_SIZE))
    offset = (page - 1) * page_size
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, timestamp, user_id, user_name, prompt, mode,
                      search_ms, prompt_build_ms, ollama_connect_ms,
                      ttft_ms, user_ttft_ms, stream_total_ms, refused
               FROM chat_perf_log
               ORDER BY id DESC
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        )
        rows = await cursor.fetchall()
        count_cursor = await db.execute("SELECT COUNT(*) as c FROM chat_perf_log")
        total = dict(await count_cursor.fetchone())["c"]
        return {
            "entries": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }
    finally:
        await db.close()


@router.get("/perf/{entry_id}")
async def admin_perf_entry(
    entry_id: int,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Full detail for one perf log entry — includes thoughts and full response text."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM chat_perf_log WHERE id = ?", (entry_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Entry not found")
        return dict(row)
    finally:
        await db.close()


# ── Runtime Configuration ────────────────────────────────────────────────────

@router.get("/config")
async def admin_get_config(request: Request, user: dict = Depends(require_admin)):
    """Return current runtime configuration (context window, system prompt, rules)."""
    settings = get_settings()
    return {
        "num_ctx": settings.OLLAMA_NUM_CTX,
        "system_prompt": settings.SYSTEM_PROMPT_OVERRIDE or "",
        "system_rules": settings.SYSTEM_RULES_OVERRIDE or "",
        "model": settings.OLLAMA_MODEL,
    }


@router.put("/config")
async def admin_update_config(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    """Update runtime configuration.

    Accepted fields (all optional):
    - ``num_ctx`` (int)   — context window; triggers a model reload in Ollama
    - ``system_prompt``   — replaces the built-in system prompt (empty string = reset)
    - ``system_rules``    — extra rules appended to whichever prompt is active
    """
    body = await request.json()
    settings = get_settings()
    changed: list[str] = []
    reload_model = False

    if "num_ctx" in body:
        new_ctx = int(body["num_ctx"])
        if new_ctx < 512:
            raise HTTPException(400, "num_ctx must be at least 512")
        if new_ctx != settings.OLLAMA_NUM_CTX:
            settings.OLLAMA_NUM_CTX = new_ctx
            changed.append("num_ctx")
            reload_model = True

    if "system_prompt" in body:
        val = (body["system_prompt"] or "").strip()
        settings.SYSTEM_PROMPT_OVERRIDE = val or None
        changed.append("system_prompt")

    if "system_rules" in body:
        val = (body["system_rules"] or "").strip()
        settings.SYSTEM_RULES_OVERRIDE = val or None
        changed.append("system_rules")

    if changed:
        settings.save_admin_config()
        log_event("admin_config_updated", user_id=user["user_id"], changed=",".join(changed))

    if reload_model and settings.OLLAMA_MODEL:
        background_tasks.add_task(
            _reload_model_with_ctx, settings.OLLAMA_MODEL, settings.OLLAMA_NUM_CTX
        )

    return {
        "status": "ok",
        "changed": changed,
        "num_ctx": settings.OLLAMA_NUM_CTX,
        "system_prompt": settings.SYSTEM_PROMPT_OVERRIDE or "",
        "system_rules": settings.SYSTEM_RULES_OVERRIDE or "",
        "reloading": reload_model,
    }


async def _reload_model_with_ctx(name: str, num_ctx: int) -> None:
    """Unload the model then reload it with the new context window size."""
    try:
        await unload_model(name)
        await preload_model(name, num_ctx=num_ctx)
        logging.info(f"admin: reloaded '{name}' with num_ctx={num_ctx}")
    except Exception as e:
        logging.warning(f"admin: failed to reload '{name}' with num_ctx={num_ctx}: {e}")


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


# ── Suggestions CRUD ─────────────────────────────────────────────────────────

def _suggestions_path() -> Path:
    return get_demo_index_dir() / "suggestions.json"


def _read_suggestions() -> list[str]:
    path = _suggestions_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("suggestions", [])
    except Exception:
        return []


def _write_suggestions(items: list[str]) -> None:
    path = _suggestions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"suggestions": items}, indent=2), encoding="utf-8")


@router.get("/demo/suggestions")
async def demo_list_suggestions(request: Request, user: dict = Depends(require_admin)):
    """Return the current list of generated suggested questions."""
    return {"suggestions": _read_suggestions()}


@router.put("/demo/suggestions")
async def demo_update_suggestions(request: Request, user: dict = Depends(require_admin)):
    """Overwrite the full suggestions list."""
    body = await request.json()
    items = body.get("suggestions", [])
    if not isinstance(items, list) or not all(isinstance(s, str) for s in items):
        raise HTTPException(400, "suggestions must be a list of strings")
    _write_suggestions(items)
    log_event("demo_suggestions_updated", user_id=user["user_id"], count=len(items))
    return {"suggestions": items}


@router.post("/demo/suggestions")
async def demo_add_suggestion(request: Request, user: dict = Depends(require_admin)):
    """Add a single question to the suggestions list."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    items = _read_suggestions()
    items.append(question)
    _write_suggestions(items)
    log_event("demo_suggestion_added", user_id=user["user_id"])
    return {"suggestions": items}


@router.delete("/demo/suggestions/{index}")
async def demo_delete_suggestion(
    index: int, request: Request, user: dict = Depends(require_admin),
):
    """Remove a suggestion by its list index."""
    items = _read_suggestions()
    if index < 0 or index >= len(items):
        raise HTTPException(404, "Suggestion index out of range")
    removed = items.pop(index)
    _write_suggestions(items)
    log_event("demo_suggestion_deleted", user_id=user["user_id"], question=removed[:80])
    return {"suggestions": items}


# ── Default Q&A / STAR Stories CRUD ──────────────────────────────────────────

def _qa_path() -> Path:
    return get_settings().DATA_DIR / "demo_default_qa.json"


def _read_qa() -> list[dict]:
    path = _qa_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])
    except Exception:
        return []


def _write_qa(items: list[dict]) -> None:
    path = _qa_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")


@router.get("/demo/qa")
async def demo_list_qa(request: Request, user: dict = Depends(require_admin)):
    """List all default Q&A and STAR story items."""
    return {"items": _read_qa()}


@router.post("/demo/qa")
async def demo_create_qa(request: Request, user: dict = Depends(require_admin)):
    """Create a new Q&A or STAR story item."""
    import uuid
    body = await request.json()
    item_type = body.get("type", "qa")
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    if item_type not in ("qa", "star"):
        raise HTTPException(400, "type must be 'qa' or 'star'")

    item: dict = {"id": str(uuid.uuid4()), "type": item_type, "question": question}
    if item_type == "qa":
        item["answer"] = (body.get("answer") or "").strip()
    else:
        for field in ("situation", "task", "action", "result"):
            item[field] = (body.get(field) or "").strip()

    items = _read_qa()
    items.append(item)
    _write_qa(items)
    log_event("demo_qa_created", user_id=user["user_id"], item_type=item_type)
    return {"item": item, "items": items}


@router.put("/demo/qa/{item_id}")
async def demo_update_qa(
    item_id: str, request: Request, user: dict = Depends(require_admin),
):
    """Update an existing Q&A or STAR story item."""
    body = await request.json()
    items = _read_qa()
    target = next((i for i in items if i["id"] == item_id), None)
    if not target:
        raise HTTPException(404, "Item not found")

    if "question" in body:
        target["question"] = (body["question"] or "").strip()
    if "type" in body and body["type"] in ("qa", "star"):
        target["type"] = body["type"]
    if target["type"] == "qa":
        if "answer" in body:
            target["answer"] = (body["answer"] or "").strip()
    else:
        for field in ("situation", "task", "action", "result"):
            if field in body:
                target[field] = (body[field] or "").strip()

    _write_qa(items)
    log_event("demo_qa_updated", user_id=user["user_id"], item_id=item_id)
    return {"item": target, "items": items}


@router.delete("/demo/qa/{item_id}")
async def demo_delete_qa(
    item_id: str, request: Request, user: dict = Depends(require_admin),
):
    """Delete a Q&A or STAR story item."""
    items = _read_qa()
    before = len(items)
    items = [i for i in items if i["id"] != item_id]
    if len(items) == before:
        raise HTTPException(404, "Item not found")
    _write_qa(items)
    log_event("demo_qa_deleted", user_id=user["user_id"], item_id=item_id)
    return {"items": items}
