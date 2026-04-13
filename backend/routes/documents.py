# -*- coding: utf-8 -*-
"""Document management routes — upload, list, delete."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Depends

from backend.auth.middleware import require_auth
from backend.storage import (
    list_user_documents, save_uploaded_file, delete_user_document,
    get_user_upload_dir, get_user_index_dir,
    get_user_chunking_config, save_user_chunking_config,
    get_user_token_metrics,
    get_user_agent_config, save_user_agent_config,
    get_user_total_upload_size, delete_user_data,
    get_preserve_data_flag, set_preserve_data_flag,
    MAX_USER_UPLOAD_BYTES,
)
from backend.logger import log_event

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".pptx", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.get("/")
async def list_documents(request: Request, user: dict = Depends(require_auth)):
    """List all documents for the authenticated user."""
    docs = list_user_documents(user["user_id"])
    return {"documents": docs, "count": len(docs)}


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
):
    """Upload a document for the authenticated user."""
    if not file.filename:
        raise HTTPException(400, "Filename is required")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)} MB")

    # Enforce 2 GB total upload limit per user
    current_total = get_user_total_upload_size(user["user_id"])
    if current_total + len(content) > MAX_USER_UPLOAD_BYTES:
        used_mb = round(current_total / (1024 * 1024))
        limit_gb = MAX_USER_UPLOAD_BYTES // (1024 * 1024 * 1024)
        raise HTTPException(
            400,
            f"Upload would exceed the {limit_gb} GB total limit. "
            f"Currently using {used_mb} MB. Delete some files first.",
        )

    # Sanitize filename
    safe_name = Path(file.filename).name
    result = save_uploaded_file(user["user_id"], safe_name, content)

    log_event("document_upload", user_id=user["user_id"], filename=safe_name, size=len(content))
    return {"status": "uploaded", **result}


@router.delete("/{filename}")
async def delete_document(
    filename: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    """Delete a specific document for the authenticated user."""
    deleted = delete_user_document(user["user_id"], filename)
    if not deleted:
        raise HTTPException(404, "Document not found")

    log_event("document_delete", user_id=user["user_id"], filename=filename)
    return {"status": "deleted", "filename": filename}


@router.get("/stats")
async def document_stats(request: Request, user: dict = Depends(require_auth)):
    """Get document and index stats for the authenticated user."""
    docs = list_user_documents(user["user_id"])
    index_dir = get_user_index_dir(user["user_id"])
    detail_dir = index_dir / "detail"

    chunk_count = 0
    categories = []
    if detail_dir.exists():
        for f in detail_dir.glob("chunks.*.jsonl"):
            if f.name == "chunks.jsonl":
                continue
            cat = f.stem.replace("chunks.", "")
            count = sum(1 for line in open(f, encoding="utf-8") if line.strip())
            chunk_count += count
            categories.append({"category": cat, "chunks": count})

    return {
        "documents": len(docs),
        "total_size_bytes": sum(d["size_bytes"] for d in docs),
        "indexed_chunks": chunk_count,
        "categories": categories,
    }


@router.get("/config")
async def get_chunking_config(request: Request, user: dict = Depends(require_auth)):
    """Get the user's chunking configuration."""
    return get_user_chunking_config(user["user_id"])


@router.put("/config")
async def update_chunking_config(request: Request, user: dict = Depends(require_auth)):
    """Update the user's chunking configuration."""
    body = await request.json()

    if "chunk_size" in body:
        val = int(body["chunk_size"])
        if not (50 <= val <= 2000):
            raise HTTPException(400, "chunk_size must be between 50 and 2000")
    if "chunk_overlap" in body:
        val = int(body["chunk_overlap"])
        if not (0 <= val <= 500):
            raise HTTPException(400, "chunk_overlap must be between 0 and 500")
    if "chunk_overlap" in body and "chunk_size" in body:
        if int(body["chunk_overlap"]) >= int(body["chunk_size"]):
            raise HTTPException(400, "chunk_overlap must be less than chunk_size")

    saved = save_user_chunking_config(user["user_id"], body)
    log_event("chunking_config_update", user_id=user["user_id"])
    return saved


@router.get("/metrics")
async def token_metrics(request: Request, user: dict = Depends(require_auth)):
    """Get token usage metrics for the authenticated user."""
    return get_user_token_metrics(user["user_id"])


@router.get("/agent-config")
async def get_agent_config(request: Request, user: dict = Depends(require_auth)):
    """Get the user's agent configuration (system prompt and rules overrides)."""
    config = get_user_agent_config(user["user_id"])
    # Also return admin defaults so the frontend can show them as placeholders
    from backend.config import get_settings
    settings = get_settings()
    config["default_system_prompt"] = settings.SYSTEM_PROMPT_OVERRIDE or ""
    config["default_system_rules"] = settings.SYSTEM_RULES_OVERRIDE or ""
    return config


@router.put("/agent-config")
async def update_agent_config(request: Request, user: dict = Depends(require_auth)):
    """Update the user's agent configuration (system prompt and rules)."""
    body = await request.json()
    saved = save_user_agent_config(user["user_id"], body)
    log_event("agent_config_update", user_id=user["user_id"])
    return saved


@router.delete("/all")
async def delete_all_documents(request: Request, user: dict = Depends(require_auth)):
    """Delete ALL documents and indexes for the authenticated user."""
    delete_user_data(user["user_id"])
    log_event("documents_delete_all", user_id=user["user_id"])
    return {"status": "deleted", "message": "All documents and indexes removed."}


@router.get("/preserve")
async def get_preserve(request: Request, user: dict = Depends(require_auth)):
    """Get the user's data preservation preference."""
    flag = get_preserve_data_flag(user["user_id"])
    # Include session expiry info so frontend can show retention window
    from backend.database import get_db
    db = await get_db()
    try:
        from backend.auth.middleware import SESSION_COOKIE
        token = request.cookies.get(SESSION_COOKIE)
        expires_at = None
        if token:
            cursor = await db.execute(
                "SELECT expires_at FROM sessions WHERE token = ?", (token,)
            )
            row = await cursor.fetchone()
            if row:
                expires_at = dict(row)["expires_at"]
        return {**flag, "session_expires_at": expires_at}
    finally:
        await db.close()


@router.get("/insights/{doc_id:path}")
async def get_document_insights(
    doc_id: str,
    request: Request,
    refresh: bool = False,
    user: dict = Depends(require_auth),
):
    """Return cached insights for a single document (builds on demand if missing)."""
    from backend.services.insights_service import (
        load_cached_insights, build_insights as build_one,
    )
    if not refresh:
        cached = load_cached_insights(user["user_id"], doc_id)
        if cached is not None:
            return cached
    return await build_one(user["user_id"], doc_id, force=refresh)


@router.get("/chunks")
async def list_chunks(
    request: Request,
    doc_id: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    entity: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    """Faceted search over the authenticated user's indexed chunks."""
    from collections import Counter
    from backend.services.insights_service import _iter_chunks  # noqa: WPS437

    index_dir = get_user_index_dir(user["user_id"])
    detail_dir = index_dir / "detail"
    if not detail_dir.exists():
        return {"chunks": [], "facets": {}, "total": 0}

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    q_lower = (q or "").strip().lower() or None

    cats: Counter = Counter()
    tag_counter: Counter = Counter()
    entity_counter: Counter = Counter()
    docs: Counter = Counter()

    results: list[dict] = []
    total = 0

    for chunk in _iter_chunks(detail_dir):
        meta = chunk.get("metadata") or {}
        chunk_doc = meta.get("doc_id") or ""
        chunk_cat = meta.get("nlp_category") or "general"
        chunk_tags = [t for t in (chunk.get("tags") or []) if isinstance(t, str)]
        ents_raw = meta.get("nlp_entities") or []
        chunk_entities = []
        for e in ents_raw:
            if isinstance(e, dict):
                txt = e.get("text") or e.get("value")
                if txt:
                    chunk_entities.append(txt)
            elif isinstance(e, str):
                chunk_entities.append(e)

        if doc_id and chunk_doc != doc_id:
            continue
        if category and chunk_cat != category:
            continue
        if tag and tag not in chunk_tags:
            continue
        if entity and entity not in chunk_entities:
            continue
        if q_lower:
            text_blob = (chunk.get("text_raw") or chunk.get("text") or "").lower()
            if q_lower not in text_blob:
                continue

        total += 1
        cats[chunk_cat] += 1
        docs[chunk_doc] += 1
        for t in chunk_tags:
            tag_counter[t] += 1
        for e in chunk_entities:
            entity_counter[e] += 1

        if offset <= total - 1 < offset + limit:
            results.append({
                "id": chunk.get("id"),
                "doc_id": chunk_doc,
                "category": chunk_cat,
                "tags": chunk_tags,
                "breadcrumb": meta.get("breadcrumb"),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
                "text": chunk.get("text_raw") or chunk.get("text") or "",
                "entities": chunk_entities[:10],
                "related_chunks": chunk.get("related_chunks") or [],
            })

    return {
        "chunks": results,
        "total": total,
        "facets": {
            "categories": dict(cats.most_common()),
            "tags": dict(tag_counter.most_common(30)),
            "entities": dict(entity_counter.most_common(30)),
            "documents": dict(docs.most_common()),
        },
    }


@router.put("/preserve")
async def set_preserve(request: Request, user: dict = Depends(require_auth)):
    """Set the user's data preservation preference."""
    body = await request.json()
    preserve = bool(body.get("preserve", False))
    result = set_preserve_data_flag(user["user_id"], preserve)
    log_event("preserve_data_set", user_id=user["user_id"], preserve=preserve)
    return result
