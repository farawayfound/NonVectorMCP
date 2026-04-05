# -*- coding: utf-8 -*-
"""Cookie-based session authentication middleware and dependency injection."""
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

import aiosqlite
from fastapi import Request, HTTPException

from backend.config import get_settings
from backend.database import get_db

SESSION_COOKIE = "chunkylink_session"
SESSION_DURATION_DAYS = 30


async def create_session(
    db: aiosqlite.Connection,
    user_id: str,
    request: Request,
) -> str:
    """Create a session and return the token."""
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DURATION_DAYS)
    await db.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, ip_address, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            token,
            user_id,
            now.isoformat(),
            expires.isoformat(),
            request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
        ),
    )
    await db.commit()
    return token


async def get_current_user(request: Request) -> dict | None:
    """Extract and validate session from cookie. Returns user dict or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT s.*, u.github_username, u.display_name, u.avatar_url, u.role "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        row_dict = dict(row)
        expires = datetime.fromisoformat(row_dict["expires_at"])
        if datetime.now(timezone.utc) > expires:
            await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            await db.commit()
            return None

        # Update last_seen
        await db.execute(
            "UPDATE users SET last_seen = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row_dict["user_id"]),
        )
        await db.commit()

        return {
            "user_id": row_dict["user_id"],
            "github_username": row_dict["github_username"],
            "display_name": row_dict["display_name"],
            "avatar_url": row_dict["avatar_url"],
            "role": row_dict["role"],
        }
    finally:
        await db.close()


async def require_auth(request: Request) -> dict:
    """Dependency: require any authenticated user."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(request: Request) -> dict:
    """Dependency: require admin role."""
    user = await require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def destroy_session(request: Request) -> None:
    """Remove the current session from the database."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db = await get_db()
        try:
            await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            await db.commit()
        finally:
            await db.close()
