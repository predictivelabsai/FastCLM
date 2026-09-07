from dataclasses import replace
from datetime import date

from fastclm.config import settings
from fastclm import reminders
from fastclm.services.contracts import ContractService


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
