from __future__ import annotations

from dataclasses import replace

from starlette.testclient import TestClient

from fastclm.config import settings
from fastclm.services import scim
from fastclm.services.identity import IdentityService


def test_scim_user_lifecycle_is_tenant_scoped_and_audited(fresh_db, monkeypatch):
    owner, organisation = IdentityService().create_workspace(
        "scim-owner@example.test", "Secure-passphrase1!", "SCIM Owner", "SCIM Studio",
    )
    other_owner, other_organisation = IdentityService().create_workspace(
        "other-scim@example.test", "Secure-passphrase2!", "Other Owner", "Other SCIM Studio",
    )
    configured = replace(settings, scim_token="scim-test-secret")
    monkeypatch.setattr(scim, "settings", configured)
    import web_app
    monkeypatch.setattr(web_app, "settings", configured)
    headers = {"Authorization": "Bearer scim-test-secret", "X-FastCLM-Organisation": organisation["id"]}
    other_headers = {"Authorization": "Bearer scim-test-secret", "X-FastCLM-Organisation": other_organisation["id"]}

    with TestClient(web_app.app) as client:
        config = client.get("/scim/v2/ServiceProviderConfig")
        assert config.status_code == 200
        assert config.json()["patch"]["supported"] is True
        assert client.get("/scim/v2/Users", headers={"X-FastCLM-Organisation": organisation["id"]}).status_code == 401

        created = client.post("/scim/v2/Users", headers=headers, json={
            "schemas": [scim.USER_SCHEMA], "userName": "provisioned@example.test",
            "displayName": "Provisioned User", "externalId": "idp-42", "active": True,
        })
        assert created.status_code == 201
        assert created.headers["content-type"].startswith("application/scim+json")
        resource = created.json()
        assert resource["active"] is True
        assert resource["externalId"] == "idp-42"
        assert client.get(f"/scim/v2/Users/{resource['id']}", headers=other_headers).status_code == 404

        listing = client.get("/scim/v2/Users", headers=headers, params={"filter": 'userName eq "provisioned@example.test"'})
        assert listing.json()["totalResults"] == 1
        assert listing.json()["Resources"][0]["id"] == resource["id"]

        deactivated = client.patch(f"/scim/v2/Users/{resource['id']}", headers=headers, json={
            "schemas": [scim.PATCH_SCHEMA], "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        assert deactivated.status_code == 200
        assert deactivated.json()["active"] is False
        user_id = fresh_db.one("SELECT user_id FROM scim_identities WHERE scim_id=?", (resource["id"],))["user_id"]
        assert fresh_db.one("SELECT 1 FROM memberships WHERE organisation_id=? AND user_id=?", (organisation["id"], user_id)) is None

        reactivated = client.patch(f"/scim/v2/Users/{resource['id']}", headers=headers, json={
            "schemas": [scim.PATCH_SCHEMA], "Operations": [{"op": "replace", "path": "active", "value": True}],
        })
        assert reactivated.json()["active"] is True
        assert client.delete(f"/scim/v2/Users/{resource['id']}", headers=headers).status_code == 204

    assert fresh_db.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=? AND action LIKE 'scim.user.%'", (organisation["id"],)) == 4
    assert owner and other_owner
