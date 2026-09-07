"""Idempotent Postmark obligation reminder runner."""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.services.identity import new_id, now


def due_reminders() -> list[dict]:
    today = date.today()
    horizon = (today + timedelta(days=14)).isoformat()
    return get_database().rows(
        "SELECT o.*,c.title contract_title,c.reference,u.email recipient_email,u.name recipient_name,org.name organisation_name "
        "FROM obligations o JOIN contracts c ON c.id=o.contract_id JOIN organisations org ON org.id=o.organisation_id "
        "JOIN users u ON u.id=o.owner_user_id WHERE o.status='open' AND o.due_date<>'' AND o.due_date<=? ORDER BY o.due_date",
        (horizon,),
    )


def run(*, dry_run: bool = False) -> dict:
    sent, skipped, failed = 0, 0, 0
    delivery_date = date.today().isoformat()
    for item in due_reminders():
        kind = "overdue" if item["due_date"] < delivery_date else "due_soon"
        if get_database().one("SELECT id FROM reminder_deliveries WHERE obligation_id=? AND recipient_email=? AND reminder_kind=? AND delivery_date=?", (item["id"], item["recipient_email"], kind, delivery_date)):
            skipped += 1
            continue
        if dry_run:
            sent += 1
            continue
        status, message_id = "failed", ""
        try:
            if not settings.postmark_api_token:
                raise RuntimeError("POSTMARK_API_TOKEN is not configured")
            response = httpx.post(
                "https://api.postmarkapp.com/email",
                headers={"X-Postmark-Server-Token": settings.postmark_api_token, "Content-Type": "application/json"},
                json={
                    "From": settings.from_email,
                    "To": item["recipient_email"],
                    "Subject": f"{item['reference']}: obligation {kind.replace('_', ' ')}",
                    "TextBody": f"Hello {item['recipient_name']},\n\n{item['title']} for {item['contract_title']} is due {item['due_date']}.\n\nOpen FastCLM: {settings.public_url}/contracts/{item['contract_id']}",
                    "MessageStream": "outbound",
                },
                timeout=20,
            )
            response.raise_for_status()
            message_id = str(response.json().get("MessageID", ""))
            status, sent = "sent", sent + 1
        except Exception:
            failed += 1
        with get_database().transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO reminder_deliveries(id,organisation_id,obligation_id,recipient_email,reminder_kind,delivery_date,provider_message_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (new_id(), item["organisation_id"], item["id"], item["recipient_email"], kind, delivery_date, message_id, status, now()))
    return {"sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    get_database().migrate()
    print(run())
