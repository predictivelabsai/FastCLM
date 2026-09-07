"""Preference-aware, templated, idempotent Postmark reminder runner."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, timedelta

import httpx

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.services.identity import new_id, now
from fastclm.services.notifications import NotificationService
from fastclm.services.retention import RetentionService


logger = logging.getLogger("fastclm.reminders")
_scheduler_task: asyncio.Task | None = None


def due_reminders() -> list[dict]:
    horizon = (date.today() + timedelta(days=90)).isoformat()
    return get_database().rows(
        "SELECT o.*,c.title contract_title,c.reference,u.id recipient_user_id,u.email recipient_email,u.name recipient_name,org.name organisation_name,"
        "COALESCE(p.enabled,1) preference_enabled,COALESCE(p.due_soon_days,14) due_soon_days,COALESCE(p.overdue_repeat_days,1) overdue_repeat_days "
        "FROM obligations o JOIN contracts c ON c.id=o.contract_id JOIN organisations org ON org.id=o.organisation_id "
        "JOIN users u ON u.id=o.owner_user_id LEFT JOIN reminder_preferences p ON p.organisation_id=o.organisation_id AND p.user_id=u.id "
        "WHERE o.status='open' AND o.due_date<>'' AND o.due_date<=? ORDER BY o.due_date",
        (horizon,),
    )


def _render(value: str, model: dict[str, str]) -> str:
    for key, replacement in model.items():
        value = value.replace("{{" + key + "}}", replacement)
    return value


def _templates(organisation_ids: set[str]) -> dict[tuple[str, str], dict]:
    database = get_database()
    result = {}
    for organisation_id in organisation_ids:
        creator = database.scalar("SELECT user_id FROM memberships WHERE organisation_id=? ORDER BY created_at LIMIT 1", (organisation_id,))
        if creator:
            NotificationService().seed(organisation_id, creator)
        rows = database.rows("SELECT * FROM notification_templates WHERE organisation_id=? AND active=1", (organisation_id,))
        result.update({(row["organisation_id"], row["template_key"]): row for row in rows})
    return result


def _model(item: dict, recipient: dict, overdue_days: int = 0) -> dict[str, str]:
    return {
        "recipient_name": recipient["recipient_name"],
        "obligation_title": item["title"],
        "contract_title": item["contract_title"],
        "reference": item["reference"],
        "due_date": item["due_date"],
        "overdue_days": str(overdue_days),
        "contract_url": f"{settings.public_url}/contracts/{item['contract_id']}",
        "organisation_name": item["organisation_name"],
    }


def _normal_candidates(items: list[dict], templates: dict) -> list[dict]:
    today = date.today()
    candidates = []
    for item in items:
        if not item["preference_enabled"]:
            continue
        due = date.fromisoformat(item["due_date"])
        delta = (due - today).days
        if delta < 0:
            overdue_days = -delta
            if overdue_days % int(item["overdue_repeat_days"]):
                continue
            kind = "overdue"
        elif delta <= int(item["due_soon_days"]):
            overdue_days, kind = 0, "due_soon"
        else:
            continue
        template = templates[(item["organisation_id"], kind)]
        recipient = {"recipient_user_id": item["recipient_user_id"], "recipient_email": item["recipient_email"], "recipient_name": item["recipient_name"]}
        candidates.append({**item, **recipient, "kind": kind, "delivery_date": today.isoformat(), "template": template, "escalation_rule_id": "", "model": _model(item, recipient, overdue_days)})
    return candidates


def _escalation_candidates(items: list[dict], templates: dict) -> list[dict]:
    database, today, candidates = get_database(), date.today(), []
    for item in items:
        due = date.fromisoformat(item["due_date"])
        overdue_days = (today - due).days
        if overdue_days < 0:
            continue
        rules = database.rows("SELECT * FROM reminder_escalation_rules WHERE organisation_id=? AND active=1 AND overdue_days<=? ORDER BY overdue_days", (item["organisation_id"], overdue_days))
        for rule in rules:
            if rule["recipient_user_id"]:
                recipients = database.rows("SELECT u.id recipient_user_id,u.email recipient_email,u.name recipient_name FROM users u JOIN memberships m ON m.user_id=u.id WHERE u.id=? AND m.organisation_id=?", (rule["recipient_user_id"], item["organisation_id"]))
            else:
                recipients = database.rows("SELECT u.id recipient_user_id,u.email recipient_email,u.name recipient_name FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organisation_id=? AND m.role=?", (item["organisation_id"], rule["recipient_role"]))
            for recipient in recipients:
                template = templates[(item["organisation_id"], "escalation")]
                candidates.append({**item, **recipient, "kind": f"escalation:{rule['id']}", "delivery_date": (due + timedelta(days=rule["overdue_days"])).isoformat(), "template": template, "escalation_rule_id": rule["id"], "model": _model(item, recipient, overdue_days)})
    return candidates


def _send(candidate: dict) -> tuple[str, str]:
    template, model = candidate["template"], candidate["model"]
    if not settings.postmark_api_token:
        raise RuntimeError("POSTMARK_API_TOKEN is not configured")
    common = {"From": settings.from_email, "To": candidate["recipient_email"], "MessageStream": "outbound"}
    if template["postmark_alias"]:
        url = "https://api.postmarkapp.com/email/withTemplate"
        payload = {**common, "TemplateAlias": template["postmark_alias"], "TemplateModel": model}
    else:
        url = "https://api.postmarkapp.com/email"
        text_body = _render(template["body_template"], model)
        payload = {**common, "Subject": _render(template["subject_template"], model), "TextBody": text_body, "HtmlBody": "<p>" + html.escape(text_body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"}
    response = httpx.post(url, headers={"X-Postmark-Server-Token": settings.postmark_api_token, "Content-Type": "application/json"}, json=payload, timeout=20)
    response.raise_for_status()
    return "sent", str(response.json().get("MessageID", ""))


def run(*, dry_run: bool = False) -> dict:
    sent, skipped, failed = 0, 0, 0
    items = due_reminders()
    templates = _templates({item["organisation_id"] for item in items})
    candidates = _normal_candidates(items, templates) + _escalation_candidates(items, templates)
    for item in candidates:
        existing = get_database().one(
            "SELECT id,status FROM reminder_deliveries WHERE obligation_id=? AND recipient_email=? AND reminder_kind=? AND delivery_date=?",
            (item["id"], item["recipient_email"], item["kind"], item["delivery_date"]),
        )
        if existing and existing["status"] == "sent":
            skipped += 1
            continue
        if dry_run:
            sent += 1
            continue
        try:
            status, message_id = _send(item)
            sent += 1
        except Exception:
            status, message_id, failed = "failed", "", failed + 1
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO reminder_deliveries(id,organisation_id,obligation_id,recipient_email,reminder_kind,delivery_date,provider_message_id,status,created_at,template_id,escalation_rule_id,recipient_user_id,attempt_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1) "
                "ON CONFLICT(obligation_id,recipient_email,reminder_kind,delivery_date) DO UPDATE SET provider_message_id=excluded.provider_message_id,status=excluded.status,created_at=excluded.created_at,template_id=excluded.template_id,escalation_rule_id=excluded.escalation_rule_id,recipient_user_id=excluded.recipient_user_id,attempt_count=reminder_deliveries.attempt_count+1",
                (new_id(), item["organisation_id"], item["id"], item["recipient_email"], item["kind"], item["delivery_date"], message_id, status, now(), item["template"]["id"], item["escalation_rule_id"] or None, item["recipient_user_id"] or None),
            )
    return {"sent": sent, "skipped": skipped, "failed": failed}


async def _scheduler() -> None:
    while True:
        try:
            result = await asyncio.to_thread(run)
            logger.info("Reminder cycle complete: %s", result)
            retention = await asyncio.to_thread(RetentionService().run_all)
            logger.info("Retention cycle complete: %s", retention)
        except Exception:
            logger.exception("Reminder cycle failed")
        await asyncio.sleep(settings.reminder_interval_seconds)


def start_scheduler() -> asyncio.Task | None:
    global _scheduler_task
    if not settings.reminder_scheduler_enabled or _scheduler_task:
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler(), name="fastclm-reminders")
    return _scheduler_task


async def stop_scheduler() -> None:
    global _scheduler_task
    if not _scheduler_task:
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None


if __name__ == "__main__":
    get_database().migrate()
    print(run())
