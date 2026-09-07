from dataclasses import replace

import pytest

from fastclm.config import settings
from fastclm.services import credentials
from fastclm.services.credentials import QueryLimitExceeded, authorize, clear_xai_key, get_xai_key, key_status, store_xai_key, usage


def test_byok_key_is_encrypted_and_used_without_spending_allowance(workspace, fresh_db):
    actor, _, _ = workspace
    store_xai_key(actor.user_id, "xai-example-secret-123456")
    stored = fresh_db.one("SELECT api_key_enc,api_key_hint FROM user_provider_credentials WHERE user_id=?", (actor.user_id,))
    assert b"xai-example-secret" not in bytes(stored["api_key_enc"])
    assert get_xai_key(actor.user_id) == "xai-example-secret-123456"
    assert key_status(actor.user_id)["hint"].startswith("xai-")
    key, source, reserved = authorize(actor.user_id)
    assert (key, source, reserved) == ("xai-example-secret-123456", "byok", False)
    assert usage(actor.user_id)["used"] == 0
    clear_xai_key(actor.user_id)
    assert get_xai_key(actor.user_id) is None


def test_platform_allowance_is_atomic_and_bounded(workspace, monkeypatch):
    actor, _, _ = workspace
    monkeypatch.setattr(credentials, "settings", replace(settings, xai_api_key="platform-test-key", free_query_limit=2))
    assert authorize(actor.user_id)[1:] == ("platform", True)
    assert authorize(actor.user_id)[1:] == ("platform", True)
    with pytest.raises(QueryLimitExceeded):
        authorize(actor.user_id)
    assert usage(actor.user_id)["used"] == 2
