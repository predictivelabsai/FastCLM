"""Postmark transactional email helper."""
from __future__ import annotations

import html
import re

import httpx

from fastclm.config import settings


def send_email(to: str, subject: str, html_body: str) -> bool:
    if not settings.postmark_api_token or not settings.from_email:
        return False
    response = httpx.post(
        "https://api.postmarkapp.com/email",
        headers={"X-Postmark-Server-Token": settings.postmark_api_token, "Content-Type": "application/json"},
        json={
            "From": settings.from_email,
            "To": to,
            "Subject": subject,
            "HtmlBody": html_body,
            "TextBody": re.sub(r"<[^>]+>", "", html_body),
            "MessageStream": "outbound",
        },
        timeout=20,
    )
    response.raise_for_status()
    return True


def send_account_action(email: str, name: str, subject: str, path: str) -> bool:
    link = f"{settings.public_url}{path}"
    body = (
        f"<p>Hello {html.escape(name or 'there')},</p>"
        f"<p><a href=\"{html.escape(link, quote=True)}\">{html.escape(subject)}</a></p>"
        "<p>This link expires automatically. If you did not request it, you can ignore this message.</p>"
    )
    try:
        return send_email(email, subject, body)
    except Exception:
        return False
