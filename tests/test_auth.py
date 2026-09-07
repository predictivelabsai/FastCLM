from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest

from fastclm import auth
from fastclm.config import settings


def test_google_authorisation_uses_oidc_scopes_callback_and_session_state(monkeypatch):
    configured = replace(
        settings,
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="test-secret",
        google_redirect_uri="https://clm.fastsme.com/auth/google/callback",
    )
    monkeypatch.setattr(auth, "settings", configured)
    session = {}
    query = parse_qs(urlparse(auth.google_authorize_url(session)).query)
    assert query["scope"] == ["openid email profile"]
    assert query["redirect_uri"] == [configured.google_redirect_uri]
    assert query["state"] == [session["google_oauth_state"]]


def test_google_exchange_rejects_invalid_state_before_network(monkeypatch):
    def unexpected_post(*args, **kwargs):
        raise AssertionError("network must not be called for invalid state")

    monkeypatch.setattr(auth.httpx, "post", unexpected_post)
    with pytest.raises(ValueError, match="state was invalid"):
        auth.google_exchange("code", "wrong", {"google_oauth_state": "expected"})
