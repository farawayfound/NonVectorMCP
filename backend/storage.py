# -*- coding: utf-8 -*-
"""Per-user document storage and index namespace isolation."""
import shutil
from pathlib import Path
from datetime import datetime, timezone
from backend.config import get_settings


def get_demo_upload_dir() -> Path:
    return get_settings().UPLOADS_DIR / "demo"


def get_demo_index_dir() -> Path:
    return get_settings().INDEXES_DIR / "demo"


def get_user_upload_dir(user_id: str) -> Path:
    d = get_settings().UPLOADS_DIR / "users" / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_user_index_dir(user_id: str) -> Path:
    d = get_settings().INDEXES_DIR / "users" / user_id
    for sub in ("detail", "router", "state"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def list_user_documents(user_id: str) -> list[dict]:
    upload_dir = get_user_upload_dir(user_id)
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
    return docs


def save_uploaded_file(user_id: str, filename: str, content: bytes) -> dict:
    upload_dir = get_user_upload_dir(user_id)
    dest = upload_dir / filename
    dest.write_bytes(content)
    stat = dest.stat()
    return {
        "filename": filename,
        "size_bytes": stat.st_size,
        "suffix": dest.suffix.lower(),
    }


def delete_user_document(user_id: str, filename: str) -> bool:
    upload_dir = get_user_upload_dir(user_id)
    target = upload_dir / filename
    if target.exists() and target.is_file():
        target.unlink()
        return True
    return False


def delete_user_data(user_id: str) -> None:
    """Remove all data for a user (uploads + indexes)."""
    for base in [get_settings().UPLOADS_DIR / "users" / user_id,
                 get_settings().INDEXES_DIR / "users" / user_id]:
        if base.exists():
            shutil.rmtree(base)
