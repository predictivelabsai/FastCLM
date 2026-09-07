"""Append-only audit events."""
from __future__ import annotations

import json

from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.identity import new_id, now


class AuditService:
    def record(self, actor: Actor, entity_type: str, entity_id: str, action: str, detail: dict | None = None, tx=None) -> None:
        params = (new_id(), actor.organisation_id, actor.user_id, entity_type, entity_id, action, json.dumps(detail or {}, sort_keys=True), now())
        query = "INSERT INTO audit_events(id,organisation_id,actor_user_id,entity_type,entity_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?)"
        if tx:
            tx.execute(query, params)
        else:
            with get_database().transaction() as transaction:
                transaction.execute(query, params)

    def list(self, actor: Actor, limit: int = 100) -> list[dict]:
        actor.require("audit.view")
        return get_database().rows(
            "SELECT e.*,u.name actor_name FROM audit_events e LEFT JOIN users u ON u.id=e.actor_user_id WHERE e.organisation_id=? ORDER BY e.created_at DESC LIMIT ?",
            (actor.organisation_id, min(max(limit, 1), 250)),
        )
