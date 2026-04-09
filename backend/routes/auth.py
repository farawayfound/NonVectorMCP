# -*- coding: utf-8 -*-
"""Auth routes — GitHub OAuth + invite code login + access requests."""
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse

from backend.auth.github_oauth import get_authorize_url, validate_state, exchange_code
from backend.auth.invite_codes import validate_invite, redeem_invite, create_invite
from backend.auth.middleware import (
    create_session, get_current_user, require_auth, destroy_session, SESSION_COOKIE,
)
from backend.config import get_settings
from backend.database import get_db
from backend.logger import log_event
from backend.services.email import send_invite_email

router = APIRouter()


@router.get("/github/login")
async def github_login(request: Request):
    """Redirect to GitHub OAuth authorize page."""
    settings = get_settings()
    if not settings.GITHUB_CLIENT_ID:
        return JSONResponse({"error": "GitHub OAuth not configured"}, status_code=503)
    redirect_uri = str(request.url_for("github_callback"))
    url = get_authorize_url(redirect_uri)
    return RedirectResponse(url)


@router.get("/github/callback", name="github_callback")
async def github_callback(request: Request, code: str = "", state: str = ""):
    """Handle GitHub OAuth callback."""
    if not code or not validate_state(state):
        return RedirectResponse("/?error=auth_failed")

    redirect_uri = str(request.url_for("github_callback"))
    user_info = await exchange_code(code, redirect_uri)
    if not user_info:
        return RedirectResponse("/?error=auth_failed")

    db = await get_db()
    try:
        # Upsert user
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute("SELECT id FROM users WHERE id = ?", (user_info["github_id"],))
        existing = await cursor.fetchone()
        if existing:
            await db.execute(
                "UPDATE users SET github_username=?, display_name=?, avatar_url=?, role=?, last_seen=? WHERE id=?",
                (user_info["github_username"], user_info["display_name"],
                 user_info["avatar_url"], user_info["role"], now, user_info["github_id"]),
            )
        else:
            await db.execute(
                "INSERT INTO users (id, github_username, display_name, avatar_url, role, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_info["github_id"], user_info["github_username"], user_info["display_name"],
                 user_info["avatar_url"], user_info["role"], now, now),
            )
        await db.commit()

        token = await create_session(db, user_info["github_id"], request)
        log_event("login", method="github", user_id=user_info["github_id"],
                  role=user_info["role"], username=user_info["github_username"])

        response = RedirectResponse("/")
        response.set_cookie(
            SESSION_COOKIE, token,
            httponly=True, samesite="lax", max_age=30 * 86400,
        )
        return response
    finally:
        await db.close()


@router.post("/invite")
async def invite_login(request: Request):
    """Validate an invite code and create a session."""
    body = await request.json()
    code = body.get("code", "").strip().upper()
    if not code:
        return JSONResponse({"error": "Invite code required"}, status_code=400)

    db = await get_db()
    try:
        valid = await validate_invite(db, code)
        if not valid:
            log_event("login_failed", method="invite", code_prefix=code[:4])
            return JSONResponse({"error": "Invalid or expired invite code"}, status_code=401)

        user_id = await redeem_invite(db, code)
        token = await create_session(db, user_id, request)
        log_event("login", method="invite", user_id=user_id, code_prefix=code[:4])

        response = JSONResponse({"ok": True, "user_id": user_id})
        response.set_cookie(
            SESSION_COOKIE, token,
            httponly=True, samesite="lax", max_age=30 * 86400,
        )
        return response
    finally:
        await db.close()


@router.post("/request-access")
async def request_access(request: Request):
    """Accept an email address and send an invite code to it."""
    body = await request.json()
    email = body.get("email", "").strip().lower()

    if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JSONResponse({"error": "A valid email address is required"}, status_code=400)

    client_ip = request.client.host if request.client else ""
    settings = get_settings()

    if not settings.SMTP_HOST:
        return JSONResponse(
            {"error": "Email service is not configured. Please contact the site administrator."},
            status_code=503,
        )

    db = await get_db()
    try:
        # Rate limit: max 3 access requests per email per day
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM access_requests WHERE email = ? AND created_at > ?",
            (email, cutoff),
        )
        row = await cursor.fetchone()
        if row and row[0] >= 3:
            return JSONResponse(
                {"error": "Too many requests for this email. Please try again later."},
                status_code=429,
            )

        # Create a single-use invite code that expires in 48 hours
        expires = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        code = await create_invite(
            db, created_by="system:request-access", label=f"Requested by {email}",
            max_uses=1, expires_at=expires,
        )

        # Record the request (logs the email for tracking)
        await db.execute(
            "INSERT INTO access_requests (email, invite_code, ip_address, status) VALUES (?, ?, ?, ?)",
            (email, code, client_ip, "pending"),
        )
        await db.commit()

        # Email the code — never return it directly
        sent = await send_invite_email(email, code)
        status = "sent" if sent else "email_failed"
        await db.execute(
            "UPDATE access_requests SET status = ? WHERE invite_code = ?",
            (status, code),
        )
        await db.commit()

        log_event("access_requested", email=email, code_prefix=code[:4], sent=sent)

        if not sent:
            return JSONResponse(
                {"error": "Failed to send email. Please try again later."},
                status_code=500,
            )

        return JSONResponse({"ok": True, "message": "Access code sent! Check your email."})
    finally:
        await db.close()


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return current user info, or null if not authenticated."""
    return {"user": user}


@router.get("/status")
async def auth_status(user: dict = Depends(get_current_user)):
    settings = get_settings()
    return {
        "authenticated": user is not None,
        "user": user,
        "github_enabled": bool(settings.GITHUB_CLIENT_ID),
    }


@router.post("/logout")
async def logout(request: Request):
    await destroy_session(request)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response
