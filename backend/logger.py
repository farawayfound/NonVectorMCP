# -*- coding: utf-8 -*-
"""Structured JSON-lines access logging with per-request session context."""
import json
import logging
import os
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from backend.config import get_settings


_session_ctx: ContextVar[dict] = ContextVar("session_ctx", default={})

# Events that are too noisy for the activity_log DB table
_SKIP_DB_EVENTS = frozenset({"request_start", "request_end"})


def set_session(data: dict) -> None:
    _session_ctx.set(data)


def get_session() -> dict:
    return _session_ctx.get()


_access_log = logging.getLogger("chunkylink.access")
_access_log.setLevel(logging.INFO)
_access_log.propagate = False
_handler_initialised = False


def _ensure_handler() -> None:
    global _handler_initialised
    if _handler_initialised:
        return
    try:
        settings = get_settings()
        log_path = settings.LOG_DIR / "access.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = TimedRotatingFileHandler(
            log_path, when="midnight", backupCount=30, encoding="utf-8", utc=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _access_log.addHandler(handler)
    except Exception:
        pass
    _handler_initialised = True


def _write_to_db(event: str, user_id: str | None, details: str | None) -> None:
    """Write event to the activity_log database table (sync, fast)."""
    try:
        settings = get_settings()
        settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.DB_PATH), timeout=5)
        conn.execute(
            "INSERT INTO activity_log (event, user_id, details) VALUES (?, ?, ?)",
            (event, user_id, details),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_event(event: str, **fields) -> None:
    """Write one JSON-lines record to access.log and to the activity_log DB table."""
    _ensure_handler()
    session = get_session()
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "pid": os.getpid(),
        **session,
        **fields,
    }
    _access_log.info(json.dumps(record, ensure_ascii=False, default=str))

    # Also persist to the database (skip noisy per-request events)
    if event not in _SKIP_DB_EVENTS:
        user_id = fields.get("user_id") or session.get("user_id")
        detail_fields = {k: v for k, v in fields.items() if k != "user_id"}
        details = json.dumps(detail_fields, ensure_ascii=False, default=str) if detail_fields else None
        _write_to_db(event, user_id, details)
