"""Encrypted per-user provider credentials and atomic starter allowance."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.services.identity import now


class QueryLimitExceeded(PermissionError):
    """Raised when a user has exhausted the platform-funded allowance."""


def _fernet() -> Fernet:
    if settings.encryption_key:
        key = settings.encryption_key.encode()
    else:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret.encode()).digest())
    return Fernet(key)


def store_xai_key(user_id: str, api_key: str) -> None:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("A non-empty xAI API key is required")
    hint = f"{api_key[:4]}…{api_key[-4:]}" if len(api_key) >= 10 else "configured"
    encrypted = _fernet().encrypt(api_key.encode())
    created = now()
    with get_database().transaction() as tx:
        tx.execute(
            "INSERT INTO user_provider_credentials(user_id,provider,api_key_enc,api_key_hint,created_at,updated_at) VALUES (?,'xai',?,?,?,?) "
            "ON CONFLICT(user_id,provider) DO UPDATE SET api_key_enc=excluded.api_key_enc,api_key_hint=excluded.api_key_hint,updated_at=excluded.updated_at",
            (user_id, encrypted, hint, created, created),
        )


def get_xai_key(user_id: str) -> str | None:
    row = get_database().one("SELECT api_key_enc FROM user_provider_credentials WHERE user_id=? AND provider='xai'", (user_id,))
    if not row:
        return None
    try:
        value = row["api_key_enc"]
        return _fernet().decrypt(bytes(value)).decode()
    except (InvalidToken, ValueError):
        return None


def key_status(user_id: str) -> dict:
    row = get_database().one("SELECT api_key_hint FROM user_provider_credentials WHERE user_id=? AND provider='xai'", (user_id,))
    return {"configured": bool(row), "hint": row["api_key_hint"] if row else ""}


def clear_xai_key(user_id: str) -> None:
    with get_database().transaction() as tx:
        tx.execute("DELETE FROM user_provider_credentials WHERE user_id=? AND provider='xai'", (user_id,))


def usage(user_id: str) -> dict:
    used = int(get_database().scalar("SELECT platform_queries_used FROM user_ai_allowances WHERE user_id=?", (user_id,)) or 0)
    limit = settings.free_query_limit
    has_byok = key_status(user_id)["configured"]
    return {"used": used, "limit": limit, "remaining": max(limit - used, 0), "has_byok": has_byok, "source": "byok" if has_byok else "platform"}


def authorize(user_id: str) -> tuple[str, str, bool]:
    own_key = get_xai_key(user_id)
    if own_key:
        return own_key, "byok", False
    if not settings.xai_api_key:
        raise QueryLimitExceeded("AI review is not configured. Add your own xAI API key in Settings.")
    with get_database().transaction() as tx:
        tx.execute("INSERT OR IGNORE INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, now()))
        row = tx.one(
            "UPDATE user_ai_allowances SET platform_queries_used=platform_queries_used+1,updated_at=? "
            "WHERE user_id=? AND platform_queries_used<? RETURNING platform_queries_used",
            (now(), user_id, settings.free_query_limit),
        )
    if not row:
        raise QueryLimitExceeded(f"Your {settings.free_query_limit} included AI reviews are used. Add your xAI API key in Settings to continue.")
    return settings.xai_api_key, "platform", True


def refund(user_id: str, reserved: bool) -> None:
    if not reserved:
        return
    with get_database().transaction() as tx:
        tx.execute("UPDATE user_ai_allowances SET platform_queries_used=MAX(platform_queries_used-1,0),updated_at=? WHERE user_id=?", (now(), user_id))
