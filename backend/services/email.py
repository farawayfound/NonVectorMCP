# -*- coding: utf-8 -*-
"""Email service for sending invite codes to users."""
import logging
from email.message import EmailMessage

import aiosmtplib

from backend.config import get_settings


async def send_invite_email(to_email: str, invite_code: str) -> bool:
    """Send an invite code to the given email address. Returns True on success."""
    settings = get_settings()

    if not settings.SMTP_HOST:
        logging.warning("email: SMTP not configured — skipping send to %s", to_email)
        return False

    msg = EmailMessage()
    msg["Subject"] = "Your ChunkyPotato Access Code"
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to_email
    msg.set_content(
        f"Hi there!\n\n"
        f"Here is your access code for ChunkyPotato:\n\n"
        f"    {invite_code}\n\n"
        f"Enter this code on the login page to get started.\n\n"
        f"This code is single-use and expires in 48 hours.\n\n"
        f"— ChunkyPotato"
    )
    msg.add_alternative(
        f"""<html><body style="font-family: -apple-system, sans-serif; color: #e4e6ed; background: #0f1117; padding: 40px;">
        <div style="max-width: 480px; margin: 0 auto; background: #1a1d27; border: 1px solid #2a2e3d; border-radius: 12px; padding: 40px;">
            <h2 style="color: #6366f1; margin-top: 0;">Your Access Code</h2>
            <p style="color: #8b8fa3;">Here is your access code for ChunkyPotato:</p>
            <div style="background: #0f1117; border: 1px solid #2a2e3d; border-radius: 8px; padding: 20px; text-align: center; margin: 24px 0;">
                <code style="font-size: 28px; letter-spacing: 4px; color: #e4e6ed; font-family: 'JetBrains Mono', monospace;">{invite_code}</code>
            </div>
            <p style="color: #8b8fa3;">Enter this code on the login page to get started.</p>
            <p style="color: #8b8fa3; font-size: 13px;">This code is single-use and expires in 48 hours.</p>
        </div>
        </body></html>""",
        subtype="html",
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS,
        )
        logging.info("email: invite code sent to %s", to_email)
        return True
    except Exception:
        logging.error("email: failed to send to %s", to_email, exc_info=True)
        return False
