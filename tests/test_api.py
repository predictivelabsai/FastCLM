import json
from dataclasses import replace

from starlette.testclient import TestClient

from fastclm.config import settings
from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService
from web import api as api_module
from web import api_core


def test_private_api_pagination_tenant_scope_and_audited_write(workspace, monkeypatch):
    actor, _, organisation = workspace
    contract = ContractService().create(actor, {"title": "API agreement"})
    identity = IdentityService()
    _, other_org = identity.create_workspace(
        "api-other@example.test", "Another-secure-password1!", "Other", "API Other"
    )
    configured = replace(settings, api_token="integration-test-token")
    monkeypatch.setattr(api_core, "settings", configured)
    monkeypatch.setattr(api_module, "settings", configured)

    from web_app import app

    headers = {
        "Authorization": "Bearer integration-test-token",
        "X-FastCLM-Organisation": organisation["id"],
    }
    with TestClient(app) as client:
        response = client.get("/api/v1/contracts?limit=1&offset=0", headers=headers)
        assert response.status_code == 200
        assert response.json()["meta"] == {"total": 1, "limit": 1, "offset": 0}
        assert response.json()["data"][0]["id"] == contract["id"]
        assert client.get(
            "/api/v1/contracts", headers=headers | {"X-FastCLM-Organisation": other_org["id"]}
        ).json()["meta"]["total"] == 0
        assert client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).status_code == 200
        assert client.get(
            f"/api/v1/contracts/{contract['id']}",
            headers=headers | {"X-FastCLM-Organisation": other_org["id"]},
        ).status_code == 404

        payload = {"contract_id": contract["id"], "title": "Send notice", "due_date": "2026-11-01"}
        assert client.post("/api/v1/obligations", headers=headers, json=payload).status_code == 403
        created = client.post(
            "/api/v1/obligations",
            headers=headers | {"X-FastCLM-Actor": actor.user_id},
            json=payload,
        )
        assert created.status_code == 201
        assert created.json()["title"] == "Send notice"
        assert client.get(
            f"/api/v1/obligations/{created.json()['id']}", headers=headers
        ).status_code == 200


def test_openapi_snapshot_matches_runtime(fresh_db):
    from web.api import api

    with open("swagger.json", encoding="utf-8") as stream:
        committed = json.load(stream)
    assert committed == api.openapi()
