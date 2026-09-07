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


MANAGED_ROLES = {"admin", "legal", "approver", "member"}


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
        from fastclm.services.skills import SkillService
        SkillService().seed(organisation_id, user_id)
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
        from fastclm.services.skills import SkillService
        SkillService().seed(organisation_id, user_id)
        return self.user(user_id), self.organisation(organisation_id)

    def ensure_oauth_user(self, email: str, name: str) -> dict:
        """Return a verified OAuth user without implicitly creating a workspace."""
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("A valid email is required")
        db = get_database()
        user = db.one("SELECT id FROM users WHERE email=?", (email,))
        if user:
            with db.transaction() as tx:
                tx.execute("UPDATE users SET is_verified=1,name=? WHERE id=?", ((name or email.split("@", 1)[0]).strip(), user["id"]))
            return self.user(user["id"])
        user_id, created = new_id(), now()
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,1)",
                (user_id, email, (name or email.split("@", 1)[0]).strip(), None, created),
            )
            tx.execute("INSERT INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, created))
        return self.user(user_id)

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

    def team(self, actor: Actor) -> dict:
        members = get_database().rows(
            "SELECT m.user_id,m.role,m.created_at,u.name,u.email FROM memberships m "
            "JOIN users u ON u.id=m.user_id WHERE m.organisation_id=? ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,u.name",
            (actor.organisation_id,),
        )
        invitations = get_database().rows(
            "SELECT i.id,i.email,i.role,i.expires_at,i.created_at,u.name invited_by_name FROM team_invitations i "
            "JOIN users u ON u.id=i.invited_by WHERE i.organisation_id=? AND i.accepted_at IS NULL "
            "AND i.revoked_at IS NULL AND i.expires_at>? ORDER BY i.created_at DESC",
            (actor.organisation_id, int(time.time())),
        )
        return {"members": members, "invitations": invitations}

    def invite(self, actor: Actor, email: str, role: str, ttl_seconds: int = 7 * 24 * 3600) -> tuple[dict, str]:
        from fastclm.services.audit import AuditService

        actor.require("team.manage")
        email, role = email.strip().lower(), role.strip().lower()
        if "@" not in email:
            raise ValueError("A valid email is required")
        if role not in MANAGED_ROLES:
            raise ValueError("Choose an administrator, legal, approver, or member role")
        value, created, expires = secrets.token_urlsafe(32), now(), int(time.time()) + max(3600, ttl_seconds)
        digest = hashlib.sha256(value.encode()).hexdigest()
        invitation_id = new_id()
        with get_database().transaction() as tx:
            if tx.one(
                "SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organisation_id=? AND u.email=?",
                (actor.organisation_id, email),
            ):
                raise ValueError("That person is already a workspace member")
            tx.execute(
                "UPDATE team_invitations SET revoked_at=? WHERE organisation_id=? AND email=? "
                "AND accepted_at IS NULL AND revoked_at IS NULL",
                (int(time.time()), actor.organisation_id, email),
            )
            tx.execute(
                "INSERT INTO team_invitations(id,organisation_id,email,role,token_hash,invited_by,expires_at,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (invitation_id, actor.organisation_id, email, role, digest, actor.user_id, expires, created),
            )
            AuditService().record(actor, "team_invitation", invitation_id, "team.invitation.created", {"email": email, "role": role}, tx)
        return get_database().one("SELECT id,email,role,expires_at,created_at FROM team_invitations WHERE id=?", (invitation_id,)), value

    def invitation(self, value: str) -> dict | None:
        digest = hashlib.sha256(value.encode()).hexdigest()
        return get_database().one(
            "SELECT i.id,i.organisation_id,i.email,i.role,i.expires_at,o.name organisation_name,"
            "CASE WHEN u.id IS NULL THEN 0 ELSE 1 END existing_user FROM team_invitations i "
            "JOIN organisations o ON o.id=i.organisation_id LEFT JOIN users u ON u.email=i.email "
            "WHERE i.token_hash=? AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>?",
            (digest, int(time.time())),
        )

    def accept_invitation(self, value: str, user_id: str = "", name: str = "", password: str = "") -> tuple[dict, dict]:
        from fastclm.services.audit import AuditService

        digest, accepted = hashlib.sha256(value.encode()).hexdigest(), int(time.time())
        created_user = False
        with get_database().transaction() as tx:
            invitation = tx.one(
                "SELECT i.*,o.name organisation_name FROM team_invitations i JOIN organisations o ON o.id=i.organisation_id "
                "WHERE i.token_hash=? AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>?",
                (digest, accepted),
            )
            if not invitation:
                raise ValueError("Invitation is invalid, expired, or already used")
            if user_id:
                user = tx.one("SELECT id,email,name FROM users WHERE id=?", (user_id,))
                if not user or user["email"].lower() != invitation["email"].lower():
                    raise PermissionError("Sign in with the email address that was invited")
            else:
                if tx.one("SELECT id FROM users WHERE email=?", (invitation["email"],)):
                    raise ValueError("An account already exists. Sign in to accept this invitation")
                user_id, created_user = new_id(), True
                clean_name = name.strip()
                if not clean_name:
                    raise ValueError("Your name is required")
                tx.execute(
                    "INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,1)",
                    (user_id, invitation["email"], clean_name, hash_password(password), now()),
                )
                tx.execute("INSERT INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, now()))
                user = {"id": user_id, "email": invitation["email"], "name": clean_name}
            tx.execute(
                "INSERT OR IGNORE INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,?,?)",
                (invitation["organisation_id"], user_id, invitation["role"], now()),
            )
            tx.execute(
                "UPDATE team_invitations SET accepted_by=?,accepted_at=? WHERE id=? AND accepted_at IS NULL",
                (user_id, accepted, invitation["id"]),
            )
            invitee = Actor(user_id, user["email"], user["name"], invitation["organisation_id"], invitation["organisation_name"], invitation["role"])
            AuditService().record(invitee, "team_invitation", invitation["id"], "team.invitation.accepted", {"role": invitation["role"]}, tx)
        if created_user:
            self.seed_clauses(invitation["organisation_id"])
            from fastclm.services.skills import SkillService
            SkillService().seed(invitation["organisation_id"], user_id)
        return self.user(user_id), self.organisation(invitation["organisation_id"])

    def revoke_invitation(self, actor: Actor, invitation_id: str) -> None:
        from fastclm.services.audit import AuditService

        actor.require("team.manage")
        with get_database().transaction() as tx:
            result = tx.execute(
                "UPDATE team_invitations SET revoked_at=? WHERE id=? AND organisation_id=? "
                "AND accepted_at IS NULL AND revoked_at IS NULL",
                (int(time.time()), invitation_id, actor.organisation_id),
            )
            if result.rowcount != 1:
                raise LookupError("Pending invitation not found")
            AuditService().record(actor, "team_invitation", invitation_id, "team.invitation.revoked", {}, tx)

    def update_role(self, actor: Actor, user_id: str, role: str) -> None:
        from fastclm.services.audit import AuditService

        actor.require("team.manage")
        role = role.strip().lower()
        if role not in MANAGED_ROLES:
            raise ValueError("The owner role cannot be assigned here")
        with get_database().transaction() as tx:
            membership = tx.one("SELECT role FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, user_id))
            if not membership:
                raise LookupError("Member not found")
            if membership["role"] == "owner":
                raise ValueError("The workspace owner role cannot be changed")
            tx.execute("UPDATE memberships SET role=? WHERE organisation_id=? AND user_id=?", (role, actor.organisation_id, user_id))
            AuditService().record(actor, "membership", user_id, "team.member.role_changed", {"from": membership["role"], "to": role}, tx)

    def remove_member(self, actor: Actor, user_id: str) -> None:
        from fastclm.services.audit import AuditService

        actor.require("team.manage")
        with get_database().transaction() as tx:
            membership = tx.one("SELECT role FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, user_id))
            if not membership:
                raise LookupError("Member not found")
            if membership["role"] == "owner":
                raise ValueError("The workspace owner cannot be removed")
            tx.execute("DELETE FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, user_id))
            AuditService().record(actor, "membership", user_id, "team.member.removed", {"role": membership["role"]}, tx)

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
