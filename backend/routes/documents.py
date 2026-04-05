# -*- coding: utf-8 -*-
"""Document management routes — upload, list, delete."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Depends

from backend.auth.middleware import require_auth
from backend.storage import (
    list_user_documents, save_uploaded_file, delete_user_document,
    get_user_upload_dir, get_user_index_dir,
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
