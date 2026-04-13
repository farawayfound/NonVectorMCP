# -*- coding: utf-8 -*-
"""SQLite database layer for auth, sessions, invite codes, and activity logging."""
import aiosqlite
import sqlite3
from pathlib import Path
from backend.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    github_username TEXT,
    display_name TEXT,
    avatar_url TEXT,
    role TEXT NOT NULL DEFAULT 'recruiter',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_seen TEXT,
    email TEXT
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at TEXT,
    max_uses INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    label TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    user_id TEXT,
    event TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS chat_perf_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    user_id TEXT,
    user_name TEXT,
    prompt TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'ama',
    search_ms INTEGER,
    prompt_build_ms INTEGER,
    ollama_connect_ms INTEGER,
    ttft_ms INTEGER,
    user_ttft_ms INTEGER,
    stream_total_ms INTEGER,
    thoughts TEXT,
    response TEXT,
    refused INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    invite_code TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS library_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT,
    sources_found INTEGER NOT NULL DEFAULT 0,
    artifact_path TEXT,
    error TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_event ON activity_log(event);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_perf_ts ON chat_perf_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_library_user ON library_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_library_status ON library_tasks(status);
"""


def init_db_sync() -> None:
    """Create tables synchronously (used at startup)."""
    settings = get_settings()
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.executescript(_SCHEMA)
    # Additive migrations for databases created before chat_perf_log existed
    _migrate(conn)
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema additions to existing databases without losing data."""
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "chat_perf_log" not in existing:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_perf_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                user_id TEXT,
                user_name TEXT,
                prompt TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'ama',
                search_ms INTEGER,
                prompt_build_ms INTEGER,
                ollama_connect_ms INTEGER,
                ttft_ms INTEGER,
                user_ttft_ms INTEGER,
                stream_total_ms INTEGER,
                thoughts TEXT,
                response TEXT,
                refused INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_perf_ts ON chat_perf_log(timestamp);
        """)
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "email" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "access_requests" not in existing:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS access_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                invite_code TEXT,
                ip_address TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                status TEXT NOT NULL DEFAULT 'pending'
            );
        """)
    if "library_tasks" not in existing:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS library_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                completed_at TEXT,
                sources_found INTEGER NOT NULL DEFAULT 0,
                artifact_path TEXT,
                error TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_library_user ON library_tasks(user_id);
            CREATE INDEX IF NOT EXISTS idx_library_status ON library_tasks(status);
        """)


async def get_db() -> aiosqlite.Connection:
    """Get an async database connection."""
    settings = get_settings()
    db = await aiosqlite.connect(str(settings.DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db
