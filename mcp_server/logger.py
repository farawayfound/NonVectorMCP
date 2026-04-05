# -*- coding: utf-8 -*-
"""Structured access logging for the MCP server."""
import json, logging, os, time
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Mountain Time: UTC-7 (MDT) / UTC-6 (MST) — use fixed MDT offset; adjust if needed
_MT = timezone(timedelta(hours=-6))  # MST; change to -7 for MDT

def _mt_now() -> str:
    return datetime.now(_MT).strftime("%Y-%m-%dT%H:%M:%S%z")

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config

# ── Session context (set per-request by middleware) ───────────────────────────
_session_ctx: ContextVar[dict] = ContextVar("session_ctx", default={})

def set_session(data: dict) -> None:
    _session_ctx.set(data)

def get_session() -> dict:
    return _session_ctx.get()

# ── Logger setup ──────────────────────────────────────────────────────────────
_LOG_PATH = Path(getattr(config, "JSON_KB_DIR", "/srv/vpo_rag/JSON")) / "logs" / "mcp_access.log"

_access_log = logging.getLogger("mcp.access")
_access_log.setLevel(logging.INFO)
_access_log.propagate = False
_handler_initialised = False

class _GroupWritableRotatingHandler(TimedRotatingFileHandler):
    """Ensures rotated log files are created group-writable (664) so vpomac can append."""
    def _open(self):
        import stat
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
        except OSError:
            pass
        return stream


def _ensure_handler() -> None:
    global _handler_initialised
    if _handler_initialised:
        return
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _h = _GroupWritableRotatingHandler(
            _LOG_PATH, when="midnight", backupCount=30, encoding="utf-8", utc=False,
        )
        _h.setFormatter(logging.Formatter("%(message)s"))
        _access_log.addHandler(_h)
    except Exception:
        pass
    _handler_initialised = True


def log_event(event: str, **fields) -> None:
    """Write one JSON-lines record to mcp_access.log."""
    _ensure_handler()
    record = {
        "timestamp": _mt_now(),
        "event":     event,
        "pid":       os.getpid(),
        **get_session(),
        **fields,
    }
    _access_log.info(json.dumps(record, ensure_ascii=False, default=str))


def log_csv_ingest(table: str, filename: str, status: str,
                   rows_inserted: int = 0, rows_updated: int = 0,
                   total_rows: int = 0, error: str = None) -> None:
    """Emit a csv_ingest event directly to mcp_access.log as a plain JSON append.
    Uses direct file I/O so it works regardless of which user runs the ingest script."""
    record = {
        "timestamp":     _mt_now(),
        "event":         "csv_ingest",
        "table":         table,
        "filename":      filename,
        "status":        status,
        "rows_inserted": rows_inserted,
        "rows_updated":  rows_updated,
        "total_rows":    total_rows,
    }
    if error:
        record["error"] = error
    try:
        import stat
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        # Ensure file stays group-writable after each append (handles first-create case)
        try:
            os.chmod(_LOG_PATH, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
        except OSError:
            pass
    except Exception:
        pass
