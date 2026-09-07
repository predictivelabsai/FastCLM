"""Explicit tenant retention policies for immutable-version attachments."""
from __future__ import annotations

import json

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now
from fastclm.storage import get_storage


class RetentionService:
    def policy(self, actor: Actor) -> dict:
        row = get_database().one(
            "SELECT retention_enabled,retention_days FROM organisations WHERE id=?",
            (actor.organisation_id,),
        )
        return {"enabled": bool(row["retention_enabled"]), "days": int(row["retention_days"])}

    def set_policy(self, actor: Actor, enabled: bool, days: int) -> dict:
        actor.require("team.manage")
        if days < 30 or days > 3650:
            raise ValueError("Retention must be between 30 days and 10 years")
        with get_database().transaction() as tx:
            tx.execute(
                "UPDATE organisations SET retention_enabled=?,retention_days=? WHERE id=?",
                (int(enabled), days, actor.organisation_id),
            )
            AuditService().record(actor, "organisation", actor.organisation_id, "retention.policy_updated", {"enabled": enabled, "days": days}, tx)
        return self.policy(actor)

    def eligible(self, organisation_id: str) -> list[dict]:
        policy = get_database().one(
            "SELECT retention_enabled,retention_days FROM organisations WHERE id=?",
            (organisation_id,),
        )
        if not policy or not policy["retention_enabled"]:
            return []
        return get_database().rows(
            "SELECT v.* FROM contract_versions v JOIN contracts c ON c.id=v.contract_id AND c.organisation_id=v.organisation_id "
            "WHERE v.organisation_id=? AND v.storage_path<>'' AND v.attachment_purged_at='' "
            "AND c.status IN ('expired','terminated') AND datetime(v.created_at) <= datetime('now', ?) ORDER BY v.created_at",
            (organisation_id, f"-{int(policy['retention_days'])} days"),
        )

    def run(self, organisation_id: str, actor: Actor | None = None) -> dict:
        if actor:
            actor.require("team.manage")
            if actor.organisation_id != organisation_id:
                raise PermissionError("Retention is tenant scoped")
        purged, missing = [], []
        for version in self.eligible(organisation_id):
            storage = get_storage(version["storage_backend"], settings)
            if storage.delete(version["storage_path"]):
                purged.append(version["id"])
            else:
                missing.append(version["id"])
        timestamp = now()
        with get_database().transaction() as tx:
            for version_id in purged + missing:
                tx.execute(
                    "UPDATE contract_versions SET attachment_purged_at=?,attachment_purge_reason='retention_policy' "
                    "WHERE id=? AND organisation_id=? AND attachment_purged_at=''",
                    (timestamp, version_id, organisation_id),
                )
            detail = {"purged": len(purged), "already_missing": len(missing), "run_at": timestamp}
            if actor:
                AuditService().record(actor, "organisation", organisation_id, "retention.run", detail, tx)
            elif purged or missing:
                tx.execute(
                    "INSERT INTO audit_events(id,organisation_id,actor_user_id,entity_type,entity_id,action,detail_json,created_at) VALUES (?,?,NULL,'organisation',?,'retention.run',?,?)",
                    (new_id(), organisation_id, organisation_id, json.dumps(detail, sort_keys=True), timestamp),
                )
        return {"purged": len(purged), "already_missing": len(missing)}

    def run_all(self) -> dict:
        organisations = get_database().rows("SELECT id FROM organisations WHERE retention_enabled=1")
        results = {item["id"]: self.run(item["id"]) for item in organisations}
        return {"organisations": len(results), "purged": sum(item["purged"] for item in results.values())}
