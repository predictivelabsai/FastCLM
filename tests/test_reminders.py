from dataclasses import replace
from datetime import date, timedelta

from fastclm.config import settings
from fastclm import reminders
from fastclm.services.contracts import ContractService
from fastclm.services.notifications import NotificationService


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"MessageID": "test-message"}


def test_failed_reminder_retries_then_success_is_idempotent(workspace, fresh_db, monkeypatch):
    actor, _, _ = workspace
    contract = ContractService().create(actor, {"title": "Reminder agreement"})
    ContractService().add_obligation(actor, contract["id"], {
        "title": "Issue notice",
        "due_date": date.today().isoformat(),
    })
    monkeypatch.setattr(reminders, "settings", replace(settings, postmark_api_token="postmark-test"))

    def fail(*_args, **_kwargs):
        raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(reminders.httpx, "post", fail)
    assert reminders.run() == {"sent": 0, "skipped": 0, "failed": 1}
    assert fresh_db.scalar("SELECT status FROM reminder_deliveries") == "failed"

    monkeypatch.setattr(reminders.httpx, "post", lambda *_args, **_kwargs: _Response())
    assert reminders.run() == {"sent": 1, "skipped": 0, "failed": 0}
    assert reminders.run() == {"sent": 0, "skipped": 1, "failed": 0}
    assert fresh_db.scalar("SELECT status FROM reminder_deliveries") == "sent"


def test_preferences_templates_and_escalation_paths(workspace, fresh_db, monkeypatch):
    actor, _, _ = workspace
    contract = ContractService().create(actor, {"title": "Escalation agreement"})
    obligation = ContractService().add_obligation(actor, contract["id"], {
        "title": "Deliver compliance evidence",
        "due_date": (date.today() - timedelta(days=3)).isoformat(),
    })
    service = NotificationService()
    service.save_preferences(actor, False, 7, 5)
    template = service.update_template(
        actor, "escalation", "Escalated {{reference}}", "{{obligation_title}} is {{overdue_days}} days overdue", "fastclm-escalation-v1",
    )
    rule = service.create_escalation(actor, "Escalate after two days", 2, recipient_role="owner")
    monkeypatch.setattr(reminders, "settings", replace(settings, postmark_api_token="postmark-test"))
    calls = []

    def deliver(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return _Response()

    monkeypatch.setattr(reminders.httpx, "post", deliver)
    assert reminders.run() == {"sent": 1, "skipped": 0, "failed": 0}
    assert calls[0][0].endswith("/email/withTemplate")
    assert calls[0][1]["TemplateAlias"] == "fastclm-escalation-v1"
    assert calls[0][1]["TemplateModel"]["overdue_days"] == "3"
    delivery = fresh_db.one("SELECT * FROM reminder_deliveries WHERE obligation_id=?", (obligation["id"],))
    assert delivery["template_id"] == template["id"]
    assert delivery["escalation_rule_id"] == rule["id"]
    assert reminders.run() == {"sent": 0, "skipped": 1, "failed": 0}


def test_due_soon_window_and_local_template_rendering(workspace, monkeypatch):
    actor, _, _ = workspace
    contracts = ContractService()
    contract = contracts.create(actor, {"title": "Notice agreement"})
    contracts.add_obligation(actor, contract["id"], {"title": "Issue notice", "due_date": date.today().isoformat()})
    contracts.add_obligation(actor, contract["id"], {"title": "Future action", "due_date": (date.today() + timedelta(days=1)).isoformat()})
    service = NotificationService()
    service.save_preferences(actor, True, 0, 7)
    service.update_template(actor, "due_soon", "Action: {{obligation_title}}", "Open {{reference}} by {{due_date}}")
    monkeypatch.setattr(reminders, "settings", replace(settings, postmark_api_token="postmark-test"))
    payloads = []

    def deliver(_url, **kwargs):
        payloads.append(kwargs["json"])
        return _Response()

    monkeypatch.setattr(reminders.httpx, "post", deliver)
    assert reminders.run() == {"sent": 1, "skipped": 0, "failed": 0}
    assert payloads[0]["Subject"] == "Action: Issue notice"
    assert "Future action" not in payloads[0]["TextBody"]
