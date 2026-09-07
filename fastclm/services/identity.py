"""Multi-tenant identity and membership operations."""
from __future__ import annotations

import re
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor, hash_password, verify_password


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "workspace"
    return base[:48]


class IdentityService:
    def create_workspace(self, email: str, password: str, name: str, organisation_name: str) -> tuple[dict, dict]:
        email = email.strip().lower()
        name = name.strip()
        organisation_name = organisation_name.strip()
        if "@" not in email or not name or not organisation_name:
            raise ValueError("Name, organisation, and a valid email are required")
        password_hash = hash_password(password)
        user_id, organisation_id, created = new_id(), new_id(), now()
        db = get_database()
        with db.transaction() as tx:
            if tx.one("SELECT id FROM users WHERE email=?", (email,)):
                raise ValueError("An account already exists for this email")
            slug = slugify(organisation_name)
            if tx.one("SELECT id FROM organisations WHERE slug=?", (slug,)):
                slug = f"{slug}-{organisation_id[:6]}"
            tx.execute("INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,?)", (user_id, email, name, password_hash, created, 0 if settings.require_email_verification else 1))
            tx.execute("INSERT INTO organisations(id,name,slug,created_at) VALUES (?,?,?,?)", (organisation_id, organisation_name, slug, created))
            tx.execute("INSERT INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,?,?)", (organisation_id, user_id, "owner", created))
            tx.execute("INSERT INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, created))
        self.seed_clauses(organisation_id)
        return self.user(user_id), self.organisation(organisation_id)

    def authenticate(self, email: str, password: str) -> dict | None:
        user = get_database().one("SELECT * FROM users WHERE email=? AND is_verified=1", (email.strip().lower(),))
        return user if user and verify_password(password, user["password_hash"]) else None

    def ensure_oauth_workspace(self, email: str, name: str) -> tuple[dict, dict]:
        email = email.strip().lower()
        db = get_database()
        user = db.one("SELECT * FROM users WHERE email=?", (email,))
        if user:
            memberships = self.memberships(user["id"])
            if memberships:
                with db.transaction() as tx:
                    tx.execute("UPDATE users SET is_verified=1 WHERE id=?", (user["id"],))
                return self.user(user["id"]), self.organisation(memberships[0]["organisation_id"])
        user_id, organisation_id, created = new_id(), new_id(), now()
        workspace_name = f"{(name or email.split('@')[0]).strip()}'s workspace"
        with db.transaction() as tx:
            if not user:
                tx.execute("INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,1)", (user_id, email, name or email.split("@", 1)[0], None, created))
            else:
                user_id = user["id"]
                tx.execute("UPDATE users SET is_verified=1 WHERE id=?", (user_id,))
            slug = f"{slugify(workspace_name)}-{organisation_id[:6]}"
            tx.execute("INSERT INTO organisations(id,name,slug,created_at) VALUES (?,?,?,?)", (organisation_id, workspace_name, slug, created))
            tx.execute("INSERT INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,?,?)", (organisation_id, user_id, "owner", created))
            tx.execute("INSERT OR IGNORE INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, created))
        self.seed_clauses(organisation_id)
        return self.user(user_id), self.organisation(organisation_id)

    def memberships(self, user_id: str) -> list[dict]:
        return get_database().rows(
            "SELECT m.*,o.name organisation_name FROM memberships m JOIN organisations o ON o.id=m.organisation_id WHERE m.user_id=? ORDER BY m.created_at",
            (user_id,),
        )

    def actor(self, user_id: str, organisation_id: str) -> Actor:
        row = get_database().one(
            "SELECT u.id user_id,u.email,u.name,o.id organisation_id,o.name organisation_name,m.role "
            "FROM users u JOIN memberships m ON m.user_id=u.id JOIN organisations o ON o.id=m.organisation_id "
            "WHERE u.id=? AND o.id=?",
            (user_id, organisation_id),
        )
        if not row:
            raise LookupError("Membership not found")
        return Actor(**row, is_platform_admin=row["email"] in settings.platform_admins)

    def user(self, user_id: str) -> dict:
        row = get_database().one("SELECT id,email,name,created_at FROM users WHERE id=?", (user_id,))
        if not row:
            raise LookupError("User not found")
        return row

    def organisation(self, organisation_id: str) -> dict:
        row = get_database().one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not row:
            raise LookupError("Organisation not found")
        return row

    def issue_token(self, user_id: str, purpose: str, ttl_seconds: int) -> str:
        if purpose not in {"verify", "reset"}:
            raise ValueError("Unsupported account token")
        value, created = secrets.token_urlsafe(32), int(time.time())
        with get_database().transaction() as tx:
            tx.execute("DELETE FROM auth_tokens WHERE user_id=? AND purpose=? AND used_at IS NULL", (user_id, purpose))
            tx.execute("INSERT INTO auth_tokens(id,user_id,purpose,token_hash,expires_at,created_at) VALUES (?,?,?,?,?,?)", (new_id(), user_id, purpose, hashlib.sha256(value.encode()).hexdigest(), created + ttl_seconds, created))
        return value

    def consume_verification(self, value: str) -> dict | None:
        digest, current = hashlib.sha256(value.encode()).hexdigest(), int(time.time())
        with get_database().transaction() as tx:
            row = tx.one("SELECT id,user_id FROM auth_tokens WHERE token_hash=? AND purpose='verify' AND used_at IS NULL AND expires_at>?", (digest, current))
            if not row:
                return None
            tx.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (current, row["id"]))
            tx.execute("UPDATE users SET is_verified=1 WHERE id=?", (row["user_id"],))
        return self.user(row["user_id"])

    def request_reset(self, email: str) -> tuple[dict, str] | None:
        user = get_database().one("SELECT id,email,name FROM users WHERE email=? AND is_verified=1", (email.strip().lower(),))
        if not user:
            return None
        return user, self.issue_token(user["id"], "reset", 3600)

    def reset_password(self, value: str, password: str) -> bool:
        encoded = hash_password(password)
        digest, current = hashlib.sha256(value.encode()).hexdigest(), int(time.time())
        with get_database().transaction() as tx:
            row = tx.one("SELECT id,user_id FROM auth_tokens WHERE token_hash=? AND purpose='reset' AND used_at IS NULL AND expires_at>?", (digest, current))
            if not row:
                return False
            tx.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (current, row["id"]))
            tx.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, row["user_id"]))
        return True

    def seed_clauses(self, organisation_id: str) -> None:
        db = get_database()
        if db.scalar("SELECT COUNT(*) FROM clauses WHERE organisation_id=?", (organisation_id,)):
            return
        clauses = (
            ("Mutual confidentiality", "Confidentiality", "UK / EU", "Each party must protect confidential information using at least reasonable care and use it only to perform this agreement.", "Confidentiality obligations should be mutual, purpose-limited, and subject to customary exclusions.", "Check duration, permitted recipients, compelled disclosure, and return or deletion duties."),
            ("UK GDPR processor terms", "Data protection", "UK / EU", "Where a party processes personal data on behalf of the other, the parties will comply with Article 28 UK GDPR requirements and the documented instructions in the applicable data processing schedule.", "Use a separate data processing schedule covering security, subprocessors, assistance, deletion, and audit rights.", "Confirm controller/processor roles, international transfers, breach timing, and subprocessor notice."),
            ("EU GDPR processor terms", "Data protection", "EU", "Processing on behalf of a controller will comply with Article 28 GDPR and the documented instructions in the data processing agreement.", "Attach an Article 28-compliant DPA and appropriate transfer mechanism where required.", "Confirm data location, SCC requirements, subprocessors, security measures, and deletion."),
            ("Liability cap", "Liability", "UK / EU", "Each party's aggregate liability is capped at the fees paid or payable during the twelve months preceding the event giving rise to the claim, subject to agreed exclusions.", "Use a proportionate cap with clearly identified uncapped and super-capped risks.", "Check indirect loss exclusions, data/security caps, indemnities, and mandatory-law carve-outs."),
            ("Termination for convenience", "Termination", "UK / EU", "Either party may terminate for convenience on ninety days' written notice after the initial term.", "Allow an orderly exit with notice, accrued-payment protection, and transition assistance where material.", "Check committed spend, stranded costs, data return, assistance, and survival terms."),
        )
        created = now()
        with db.transaction() as tx:
            for title, category, jurisdiction, body, fallback, guidance in clauses:
                tx.execute(
                    "INSERT INTO clauses(id,organisation_id,title,category,jurisdiction,body,fallback_body,risk_guidance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), organisation_id, title, category, jurisdiction, body, fallback, guidance, created, created),
                )
