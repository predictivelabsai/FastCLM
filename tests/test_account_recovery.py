from dataclasses import replace

from fastclm.config import settings
from fastclm.services import identity
from fastclm.services.identity import IdentityService


def test_required_email_verification_and_password_reset(fresh_db, monkeypatch):
    monkeypatch.setattr(identity, "settings", replace(settings, require_email_verification=True))
    service = IdentityService()
    user, _ = service.create_workspace("verify@example.test", "Initial-password1!", "Verify", "Verify Studio")
    assert service.authenticate("verify@example.test", "Initial-password1!") is None
    verification = service.issue_token(user["id"], "verify", 3600)
    assert service.consume_verification(verification)["id"] == user["id"]
    assert service.consume_verification(verification) is None
    assert service.authenticate("verify@example.test", "Initial-password1!")["id"] == user["id"]
    _, reset = service.request_reset("verify@example.test")
    assert service.reset_password(reset, "Replacement-password1!") is True
    assert service.reset_password(reset, "Another-password1!") is False
    assert service.authenticate("verify@example.test", "Replacement-password1!")["id"] == user["id"]


def test_google_marks_existing_local_account_verified(fresh_db, monkeypatch):
    monkeypatch.setattr(identity, "settings", replace(settings, require_email_verification=True))
    service = IdentityService()
    user, organisation = service.create_workspace("google@example.test", "Initial-password1!", "Google", "Google Studio")
    assert service.authenticate("google@example.test", "Initial-password1!") is None
    linked, linked_org = service.ensure_oauth_workspace("google@example.test", "Google User")
    assert linked["id"] == user["id"]
    assert linked_org["id"] == organisation["id"]
    assert service.authenticate("google@example.test", "Initial-password1!")["id"] == user["id"]
