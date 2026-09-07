"""Tenant-scoped SCIM 2.0 user provisioning."""
from __future__ import annotations

import json
import re

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.services.identity import new_id, now


USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
FILTER_RE = re.compile(r'^\s*(userName|externalId)\s+eq\s+"([^"]+)"\s*$', re.IGNORECASE)


class SCIMError(ValueError):
    def __init__(self, detail: str, status: int = 400, scim_type: str = "invalidValue"):
        super().__init__(detail)
        self.status = status
        self.scim_type = scim_type


class SCIMService:
    def _base(self) -> str:
        return f"{settings.public_url}/scim/v2"

    def _row(self, organisation_id: str, scim_id: str) -> dict:
        row = get_database().one(
            "SELECT s.*,u.email,COALESCE(NULLIF(s.display_name,''),u.name) scim_name,u.created_at user_created_at,m.role FROM scim_identities s "
            "JOIN users u ON u.id=s.user_id LEFT JOIN memberships m ON m.organisation_id=s.organisation_id AND m.user_id=s.user_id "
            "WHERE s.organisation_id=? AND s.scim_id=?",
            (organisation_id, scim_id),
        )
        if not row:
            raise SCIMError("User not found", 404, "notFound")
        return row

    def _resource(self, row: dict) -> dict:
        active = bool(row["active"] and row.get("role"))
        return {
            "schemas": [USER_SCHEMA],
            "id": row["scim_id"],
            "externalId": row["external_id"],
            "userName": row["email"],
            "name": {"formatted": row["scim_name"]},
            "displayName": row["scim_name"],
            "active": active,
            "emails": [{"value": row["email"], "type": "work", "primary": True}],
            "meta": {
                "resourceType": "User",
                "created": row["created_at"],
                "lastModified": row["updated_at"],
                "location": f"{self._base()}/Users/{row['scim_id']}",
            },
        }

    def _audit(self, tx, organisation_id: str, user_id: str, action: str, detail: dict) -> None:
        tx.execute(
            "INSERT INTO audit_events(id,organisation_id,actor_user_id,entity_type,entity_id,action,detail_json,created_at) "
            "VALUES (?,?,NULL,'membership',?,?,?,?)",
            (new_id(), organisation_id, user_id, action, json.dumps(detail, sort_keys=True), now()),
        )

    def list(self, organisation_id: str, filter_value: str = "", start_index: int = 1, count: int = 100) -> dict:
        where, params = "s.organisation_id=?", [organisation_id]
        if filter_value:
            match = FILTER_RE.fullmatch(filter_value)
            if not match:
                raise SCIMError("Only userName eq and externalId eq filters are supported", 400, "invalidFilter")
            column = "u.email" if match.group(1).lower() == "username" else "s.external_id"
            where += f" AND lower({column})=lower(?)"
            params.append(match.group(2))
        total = int(get_database().scalar(
            f"SELECT COUNT(*) FROM scim_identities s JOIN users u ON u.id=s.user_id WHERE {where}", tuple(params),
        ) or 0)
        safe_start, safe_count = max(1, start_index), min(max(0, count), 100)
        rows = get_database().rows(
            "SELECT s.*,u.email,COALESCE(NULLIF(s.display_name,''),u.name) scim_name,u.created_at user_created_at,m.role FROM scim_identities s "
            "JOIN users u ON u.id=s.user_id LEFT JOIN memberships m ON m.organisation_id=s.organisation_id AND m.user_id=s.user_id "
            f"WHERE {where} ORDER BY u.email LIMIT ? OFFSET ?",
            (*params, safe_count, safe_start - 1),
        )
        return {
            "schemas": [LIST_SCHEMA], "totalResults": total,
            "startIndex": safe_start, "itemsPerPage": len(rows),
            "Resources": [self._resource(row) for row in rows],
        }

    def get(self, organisation_id: str, scim_id: str) -> dict:
        return self._resource(self._row(organisation_id, scim_id))

    def create(self, organisation_id: str, data: dict) -> dict:
        email = str(data.get("userName", "")).strip().lower()
        name_value = data.get("name") if isinstance(data.get("name"), dict) else {}
        display_name = str(data.get("displayName") or name_value.get("formatted") or email.split("@", 1)[0]).strip()
        external_id = str(data.get("externalId", "")).strip()
        active = bool(data.get("active", True))
        if "@" not in email:
            raise SCIMError("userName must be a valid email address")
        created, scim_id = now(), new_id()
        with get_database().transaction() as tx:
            if external_id and tx.one("SELECT 1 FROM scim_identities WHERE organisation_id=? AND external_id=?", (organisation_id, external_id)):
                raise SCIMError("externalId already exists", 409, "uniqueness")
            user = tx.one("SELECT id FROM users WHERE email=?", (email,))
            if user:
                user_id = user["id"]
                if tx.one("SELECT 1 FROM scim_identities WHERE organisation_id=? AND user_id=?", (organisation_id, user_id)):
                    raise SCIMError("userName already exists", 409, "uniqueness")
                membership = tx.one("SELECT role FROM memberships WHERE organisation_id=? AND user_id=?", (organisation_id, user_id))
                if membership and membership["role"] != "member":
                    raise SCIMError("An elevated workspace member cannot be adopted by SCIM", 409, "mutability")
                tx.execute("UPDATE users SET is_verified=1 WHERE id=?", (user_id,))
            else:
                user_id = new_id()
                tx.execute(
                    "INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,1)",
                    (user_id, email, display_name, None, created),
                )
                tx.execute("INSERT INTO user_ai_allowances(user_id,platform_queries_used,updated_at) VALUES (?,0,?)", (user_id, created))
            if active:
                tx.execute(
                    "INSERT OR IGNORE INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,'member',?)",
                    (organisation_id, user_id, created),
                )
            tx.execute(
                "INSERT INTO scim_identities(organisation_id,user_id,scim_id,external_id,display_name,active,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (organisation_id, user_id, scim_id, external_id, display_name, int(active), created, created),
            )
            self._audit(tx, organisation_id, user_id, "scim.user.provisioned", {"external_id": external_id, "active": active})
        return self.get(organisation_id, scim_id)

    def replace(self, organisation_id: str, scim_id: str, data: dict) -> dict:
        current = self._row(organisation_id, scim_id)
        requested_email = str(data.get("userName", current["email"])).strip().lower()
        if requested_email != current["email"].lower():
            raise SCIMError("userName cannot be changed after provisioning", 400, "mutability")
        name_value = data.get("name") if isinstance(data.get("name"), dict) else {}
        display_name = str(data.get("displayName") or name_value.get("formatted") or current["scim_name"]).strip()
        external_id = str(data.get("externalId", current["external_id"])).strip()
        active = bool(data.get("active", bool(current["active"])))
        with get_database().transaction() as tx:
            if external_id and tx.one(
                "SELECT 1 FROM scim_identities WHERE organisation_id=? AND external_id=? AND scim_id<>?",
                (organisation_id, external_id, scim_id),
            ):
                raise SCIMError("externalId already exists", 409, "uniqueness")
            if active:
                tx.execute(
                    "INSERT OR IGNORE INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,'member',?)",
                    (organisation_id, current["user_id"], now()),
                )
            else:
                membership = tx.one("SELECT role FROM memberships WHERE organisation_id=? AND user_id=?", (organisation_id, current["user_id"]))
                if membership and membership["role"] == "owner":
                    raise SCIMError("The workspace owner cannot be deactivated by SCIM", 409, "mutability")
                tx.execute("DELETE FROM memberships WHERE organisation_id=? AND user_id=?", (organisation_id, current["user_id"]))
            updated = now()
            tx.execute(
                "UPDATE scim_identities SET external_id=?,display_name=?,active=?,updated_at=? WHERE organisation_id=? AND scim_id=?",
                (external_id, display_name, int(active), updated, organisation_id, scim_id),
            )
            self._audit(tx, organisation_id, current["user_id"], "scim.user.updated", {"external_id": external_id, "active": active})
        return self.get(organisation_id, scim_id)

    def patch(self, organisation_id: str, scim_id: str, data: dict) -> dict:
        if PATCH_SCHEMA not in (data.get("schemas") or []):
            raise SCIMError("PatchOp schema is required", 400, "invalidSyntax")
        current = self.get(organisation_id, scim_id)
        update = {
            "userName": current["userName"], "displayName": current["displayName"],
            "externalId": current["externalId"], "active": current["active"],
        }
        for operation in data.get("Operations") or []:
            op = str(operation.get("op", "")).lower()
            path = str(operation.get("path", "")).lower()
            value = operation.get("value")
            if op not in {"add", "replace", "remove"}:
                raise SCIMError("Unsupported PATCH operation", 400, "invalidSyntax")
            if not path and isinstance(value, dict):
                for key in ("displayName", "externalId", "active"):
                    if key in value:
                        update[key] = value[key]
                continue
            key = {"displayname": "displayName", "name.formatted": "displayName", "externalid": "externalId", "active": "active"}.get(path)
            if not key:
                raise SCIMError(f"Unsupported PATCH path: {path}", 400, "invalidPath")
            update[key] = False if key == "active" and op == "remove" else ("" if op == "remove" else value)
        return self.replace(organisation_id, scim_id, update)

    def delete(self, organisation_id: str, scim_id: str) -> None:
        self.replace(organisation_id, scim_id, {"active": False})
