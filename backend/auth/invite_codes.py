# -*- coding: utf-8 -*-
"""Invite code generation and validation."""
import secrets
import string
import uuid
from datetime import datetime, timezone

import aiosqlite


def generate_code(length: int = 8) -> str:
    """Generate a URL-safe invite code."""
    alphabet = string.ascii_uppercase + string.digits
    # Remove ambiguous characters
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("1", "").replace("L", "")
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def create_invite(
    db: aiosqlite.Connection,
    created_by: str,
    label: str = "",
    max_uses: int = 0,
    expires_at: str | None = None,
) -> str:
    """Create a new invite code. Returns the code string."""
    code = generate_code()
    await db.execute(
        "INSERT INTO invite_codes (code, created_by, label, max_uses, expires_at) VALUES (?, ?, ?, ?, ?)",
        (code, created_by, label, max_uses, expires_at),
    )
    await db.commit()
    return code


async def validate_invite(db: aiosqlite.Connection, code: str) -> dict | None:
    """Validate an invite code. Returns the code row dict if valid, None otherwise."""
    cursor = await db.execute(
        "SELECT * FROM invite_codes WHERE code = ? AND active = 1", (code,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    row_dict = dict(row)

    # Check expiration
    if row_dict["expires_at"]:
        expires = datetime.fromisoformat(row_dict["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return None

    # Check max uses
    if row_dict["max_uses"] > 0 and row_dict["use_count"] >= row_dict["max_uses"]:
        return None

    return row_dict


async def redeem_invite(db: aiosqlite.Connection, code: str) -> str:
    """Redeem an invite code — increment use count, create anonymous user. Returns user_id."""
    user_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        "UPDATE invite_codes SET use_count = use_count + 1 WHERE code = ?", (code,)
    )
    await db.execute(
        "INSERT INTO users (id, display_name, role, created_at) VALUES (?, ?, 'recruiter', ?)",
        (user_id, f"Guest ({code[:4]}...)", now),
    )
    await db.commit()
    return user_id
