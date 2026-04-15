# -*- coding: utf-8 -*-
"""Per-user document storage and index namespace isolation."""
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from backend.config import get_settings

MAX_USER_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB total per user


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


def get_user_chunking_config(user_id: str) -> dict:
    """Load per-user chunking config, falling back to global defaults."""
    settings = get_settings()
    config_path = get_user_index_dir(user_id) / "chunking_config.json"
    defaults = {
        "chunk_size": settings.PARA_TARGET_TOKENS,
        "chunk_overlap": settings.PARA_OVERLAP_TOKENS,
        "enable_nlp_tagging": settings.ENABLE_AUTO_TAGGING,
    }
    if config_path.exists():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in saved.items() if k in defaults})
        except Exception:
            pass
    return defaults


def save_user_chunking_config(user_id: str, config: dict) -> dict:
    """Persist per-user chunking config. Returns the saved config."""
    allowed_keys = {"chunk_size", "chunk_overlap", "enable_nlp_tagging"}
    current = get_user_chunking_config(user_id)
    for k, v in config.items():
        if k in allowed_keys:
            current[k] = v
    config_path = get_user_index_dir(user_id) / "chunking_config.json"
    config_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def get_user_token_metrics(user_id: str) -> dict:
    """Compute token metrics: chunks in index, tokens in chunks, tokens in raw docs, savings."""
    index_dir = get_user_index_dir(user_id)
    upload_dir = get_user_upload_dir(user_id)

    chunk_count = 0
    chunk_tokens = 0
    chunks_file = index_dir / "detail" / "chunks.jsonl"
    if chunks_file.exists():
        for line in chunks_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                text = rec.get("text_raw", rec.get("text", ""))
                chunk_count += 1
                chunk_tokens += max(1, len(text) // 4)
            except Exception:
                continue

    doc_tokens = 0
    doc_count = 0
    for f in sorted(upload_dir.iterdir()) if upload_dir.exists() else []:
        if f.is_file() and not f.name.startswith("."):
            doc_count += 1
            try:
                raw = f.read_bytes()
                doc_tokens += max(1, len(raw) // 4)
            except Exception:
                continue

    tokens_saved = max(0, doc_tokens - chunk_tokens)

    return {
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "document_tokens": doc_tokens,
        "chunk_tokens": chunk_tokens,
        "tokens_saved": tokens_saved,
        "savings_pct": round(tokens_saved / doc_tokens * 100, 1) if doc_tokens > 0 else 0,
    }


def get_user_agent_config(user_id: str) -> dict:
    """Load per-user agent config (system prompt override only).

    System rules are configured by administrators only; any legacy ``system_rules``
    key in stored JSON is ignored.
    """
    config_path = get_user_index_dir(user_id) / "agent_config.json"
    out = {"system_prompt": "", "system_rules": ""}
    if config_path.exists():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            if "system_prompt" in saved:
                out["system_prompt"] = saved["system_prompt"]
        except Exception:
            pass
    return out


def save_user_agent_config(user_id: str, config: dict) -> dict:
    """Persist per-user system prompt override. Returns the saved config."""
    allowed_keys = {"system_prompt"}
    current = get_user_agent_config(user_id)
    for k, v in config.items():
        if k in allowed_keys:
            current[k] = (v or "").strip()
    config_path = get_user_index_dir(user_id) / "agent_config.json"
    config_path.write_text(
        json.dumps({"system_prompt": current["system_prompt"]}, indent=2),
        encoding="utf-8",
    )
    return current


def get_user_total_upload_size(user_id: str) -> int:
    """Return total bytes of all uploaded files for a user."""
    upload_dir = get_settings().UPLOADS_DIR / "users" / user_id
    if not upload_dir.exists():
        return 0
    total = 0
    for f in upload_dir.iterdir():
        if f.is_file() and not f.name.startswith("."):
            total += f.stat().st_size
    return total


def _preserve_flag_path(user_id: str) -> Path:
    return get_user_index_dir(user_id) / "preserve_data.json"


def get_preserve_data_flag(user_id: str) -> dict:
    """Return the preserve-data preference for a user."""
    path = _preserve_flag_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"preserve": True}


def set_preserve_data_flag(user_id: str, preserve: bool) -> dict:
    """Set whether this user's data should survive logout/session expiry."""
    path = _preserve_flag_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"preserve": preserve}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def should_preserve_user_data(user_id: str) -> bool:
    """Check if this user opted to preserve their data."""
    return get_preserve_data_flag(user_id).get("preserve", False)


def delete_user_data(user_id: str) -> None:
    """Remove all data for a user (uploads + indexes)."""
    for base in [get_settings().UPLOADS_DIR / "users" / user_id,
                 get_settings().INDEXES_DIR / "users" / user_id]:
        if base.exists():
            shutil.rmtree(base)
