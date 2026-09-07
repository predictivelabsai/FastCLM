"""Tenant notification templates, preferences, and escalation policy."""
from __future__ import annotations

import json

from fastclm.database import get_database
from fastclm.security import Actor, PERMISSIONS
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now


DEFAULTS = {
    "due_soon": (
        "Due soon", "{{reference}}: {{obligation_title}} is due soon",
        "Hello {{recipient_name}},\n\n{{obligation_title}} for {{contract_title}} is due {{due_date}}.\n\nOpen FastCLM: {{contract_url}}",
    ),
    "overdue": (
        "Overdue", "{{reference}}: {{obligation_title}} is overdue",
        "Hello {{recipient_name}},\n\n{{obligation_title}} for {{contract_title}} was due {{due_date}} and is now overdue.\n\nOpen FastCLM: {{contract_url}}",
    ),
    "escalation": (
        "Escalation", "Escalation · {{reference}}: {{obligation_title}}",
        "Hello {{recipient_name}},\n\n{{obligation_title}} for {{contract_title}} is {{overdue_days}} days overdue and has been escalated to you.\n\nOpen FastCLM: {{contract_url}}",
    ),
}


class NotificationService:
    def seed(self, organisation_id: str, user_id: str) -> None:
        created = now()
        with get_database().transaction() as tx:
            for key, (name, subject, body) in DEFAULTS.items():
                template_id = new_id()
                inserted = tx.execute(
                    "INSERT OR IGNORE INTO notification_templates(id,organisation_id,template_key,name,subject_template,body_template,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (template_id, organisation_id, key, name, subject, body, user_id, created, created),
                )
                if inserted.rowcount:
                    tx.execute(
                        "INSERT INTO audit_events(id,organisation_id,actor_user_id,entity_type,entity_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (new_id(), organisation_id, user_id, "notification_template", template_id, "notification.template.defaulted", json.dumps({"template_key": key}), created),
                    )

    def preferences(self, actor: Actor) -> dict:
        actor.require("contracts.view")
        row = get_database().one(
            "SELECT * FROM reminder_preferences WHERE organisation_id=? AND user_id=?",
            (actor.organisation_id, actor.user_id),
        )
        return row or {"organisation_id": actor.organisation_id, "user_id": actor.user_id, "enabled": 1, "due_soon_days": 14, "overdue_repeat_days": 1}

    def save_preferences(self, actor: Actor, enabled: bool, due_soon_days: int, overdue_repeat_days: int) -> dict:
        actor.require("contracts.view")
        if not 0 <= due_soon_days <= 90:
            raise ValueError("Due-soon window must be between 0 and 90 days")
        if not 1 <= overdue_repeat_days <= 30:
            raise ValueError("Overdue cadence must be between 1 and 30 days")
        updated = now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO reminder_preferences(organisation_id,user_id,enabled,due_soon_days,overdue_repeat_days,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(organisation_id,user_id) DO UPDATE SET enabled=excluded.enabled,due_soon_days=excluded.due_soon_days,overdue_repeat_days=excluded.overdue_repeat_days,updated_at=excluded.updated_at",
                (actor.organisation_id, actor.user_id, int(enabled), due_soon_days, overdue_repeat_days, updated),
            )
            AuditService().record(actor, "reminder_preference", actor.user_id, "reminder.preferences.updated", {"enabled": enabled, "due_soon_days": due_soon_days, "overdue_repeat_days": overdue_repeat_days}, tx)
        return self.preferences(actor)

    def update_template(self, actor: Actor, template_key: str, subject: str, body: str, postmark_alias: str = "") -> dict:
        actor.require("team.manage")
        if template_key not in DEFAULTS:
            raise ValueError("Unsupported notification template")
        subject, body = subject.strip(), body.strip()
        if not subject or not body:
            raise ValueError("Template subject and body are required")
        self.seed(actor.organisation_id, actor.user_id)
        updated = now()
        with get_database().transaction() as tx:
            row = tx.one("SELECT id FROM notification_templates WHERE organisation_id=? AND template_key=?", (actor.organisation_id, template_key))
            tx.execute("UPDATE notification_templates SET subject_template=?,body_template=?,postmark_alias=?,updated_at=? WHERE id=? AND organisation_id=?", (subject, body, postmark_alias.strip(), updated, row["id"], actor.organisation_id))
            AuditService().record(actor, "notification_template", row["id"], "notification.template.updated", {"template_key": template_key, "postmark_alias": bool(postmark_alias.strip())}, tx)
        return get_database().one("SELECT * FROM notification_templates WHERE id=? AND organisation_id=?", (row["id"], actor.organisation_id))

    def create_escalation(self, actor: Actor, name: str, overdue_days: int, recipient_role: str = "", recipient_user_id: str = "") -> dict:
        actor.require("team.manage")
        name, recipient_role = name.strip(), recipient_role.strip().lower()
        if not name or not 0 <= overdue_days <= 365:
            raise ValueError("Escalation name and an overdue threshold from 0 to 365 are required")
        if recipient_role and (recipient_role not in PERMISSIONS or recipient_user_id):
            raise ValueError("Choose either one valid role or one person")
        if recipient_user_id:
            if not get_database().one("SELECT 1 FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, recipient_user_id)):
                raise LookupError("Escalation recipient is not a workspace member")
        elif not recipient_role:
            raise ValueError("Choose an escalation role or person")
        self.seed(actor.organisation_id, actor.user_id)
        template = get_database().one("SELECT id FROM notification_templates WHERE organisation_id=? AND template_key='escalation'", (actor.organisation_id,))
        rule_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO reminder_escalation_rules(id,organisation_id,name,overdue_days,recipient_role,recipient_user_id,template_id,active,created_by,created_at) VALUES (?,?,?,?,?,?,?,1,?,?)", (rule_id, actor.organisation_id, name, overdue_days, recipient_role, recipient_user_id or None, template["id"], actor.user_id, created))
            AuditService().record(actor, "reminder_escalation", rule_id, "reminder.escalation.created", {"overdue_days": overdue_days, "recipient_role": recipient_role, "recipient_user_id": recipient_user_id}, tx)
        return get_database().one("SELECT * FROM reminder_escalation_rules WHERE id=? AND organisation_id=?", (rule_id, actor.organisation_id))

    def set_escalation_active(self, actor: Actor, rule_id: str, active: bool) -> dict:
        actor.require("team.manage")
        row = get_database().one("SELECT * FROM reminder_escalation_rules WHERE id=? AND organisation_id=?", (rule_id, actor.organisation_id))
        if not row:
            raise LookupError("Escalation rule not found")
        with get_database().transaction() as tx:
            tx.execute("UPDATE reminder_escalation_rules SET active=? WHERE id=? AND organisation_id=?", (int(active), rule_id, actor.organisation_id))
            AuditService().record(actor, "reminder_escalation", rule_id, "reminder.escalation.status_changed", {"active": active}, tx)
        return get_database().one("SELECT * FROM reminder_escalation_rules WHERE id=? AND organisation_id=?", (rule_id, actor.organisation_id))

    def overview(self, actor: Actor) -> dict:
        actor.require("contracts.view")
        self.seed(actor.organisation_id, actor.user_id)
        return {
            "preferences": self.preferences(actor),
            "templates": get_database().rows("SELECT * FROM notification_templates WHERE organisation_id=? ORDER BY template_key", (actor.organisation_id,)),
            "escalations": get_database().rows("SELECT r.*,u.name recipient_name FROM reminder_escalation_rules r LEFT JOIN users u ON u.id=r.recipient_user_id WHERE r.organisation_id=? ORDER BY r.overdue_days,r.name", (actor.organisation_id,)),
            "members": get_database().rows("SELECT m.user_id,m.role,u.name FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organisation_id=? ORDER BY u.name", (actor.organisation_id,)),
        }
