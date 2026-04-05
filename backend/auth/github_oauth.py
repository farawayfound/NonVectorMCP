# -*- coding: utf-8 -*-
"""GitHub OAuth flow — admin authentication."""
import secrets
from datetime import datetime, timezone, timedelta

import httpx

from backend.config import get_settings

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# CSRF state tokens — in-memory (short-lived, single server)
_pending_states: dict[str, datetime] = {}


def get_authorize_url(redirect_uri: str) -> str:
    """Generate GitHub OAuth authorize URL with CSRF state."""
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    _pending_states[state] = datetime.now(timezone.utc)
    # Clean expired states (>10 min)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    for k in [k for k, v in _pending_states.items() if v < cutoff]:
        _pending_states.pop(k, None)
    return (
        f"{GITHUB_AUTH_URL}?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}&scope=read:user&state={state}"
    )


def validate_state(state: str) -> bool:
    """Validate and consume a CSRF state token."""
    if state in _pending_states:
        _pending_states.pop(state)
        return True
    return False


async def exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange authorization code for user info. Returns user dict or None."""
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        resp = await client.post(
            GITHUB_TOKEN_URL,
            json={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return None
        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return None

        # Fetch user profile
        resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None
        gh_user = resp.json()

    username = gh_user.get("login", "")
    is_admin = username.lower() in [a.lower() for a in settings.GITHUB_ALLOWED_ADMINS]

    return {
        "github_id": str(gh_user.get("id", "")),
        "github_username": username,
        "display_name": gh_user.get("name") or username,
        "avatar_url": gh_user.get("avatar_url", ""),
        "role": "admin" if is_admin else "recruiter",
    }
