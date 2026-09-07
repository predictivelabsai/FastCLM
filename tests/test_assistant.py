from __future__ import annotations

import json

import pytest

from fastclm.services.assistant import AssistantService
from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService, new_id, now
from fastclm.services.skills import SkillService


def test_cockpit_and_skills_are_tenant_scoped_and_versioned(workspace):
    actor, _, _ = workspace
    cockpit = AssistantService().cockpit(actor)
    assert cockpit["messages"][0]["role"] == "assistant"
    assert len(cockpit["skills"]) == 4

    skill = cockpit["skills"][0]
    updated = SkillService().update(actor, skill["id"], {
        "name": skill["name"],
        "description": skill["description"],
        "jurisdiction": skill["jurisdiction"],
        "instructions": skill["instructions"] + "\nAlways identify ambiguity.\n",
    })
    assert updated["current_version"] == 2
    assert [item["version_number"] for item in updated["versions"]] == [2, 1]

    other_user, other_org = IdentityService().create_workspace(
        "other@example.test", "A-secure-passphrase2!", "Other", "Other Studio"
    )
    other_actor = IdentityService().actor(other_user["id"], other_org["id"])
    with pytest.raises(LookupError):
        SkillService().get(other_actor, skill["id"])


def test_assistant_sources_do_not_cross_tenants(workspace, monkeypatch):
    actor, _, _ = workspace
    own = ContractService().create(actor, {"title": "Own NDA", "reference": "OWN-1"})
    ContractService().add_block(actor, own["id"], "clause", "The confidentiality term is three years.")
    ContractService().snapshot(actor, own["id"], "With term")

    other_user, other_org = IdentityService().create_workspace(
        "outside@example.test", "A-secure-passphrase3!", "Outside", "Outside Studio"
    )
    other_actor = IdentityService().actor(other_user["id"], other_org["id"])
    outside = ContractService().create(other_actor, {"title": "Outside NDA", "reference": "OUT-1"})
    ContractService().add_block(other_actor, outside["id"], "clause", "The secret outside term is ninety-nine years.")
    ContractService().snapshot(other_actor, outside["id"], "Secret")

    monkeypatch.setattr("fastclm.services.assistant.authorize", lambda _user_id: ("key", "byok", False))
    captured = {}

    def fake_xai(_self, _key, _question, sources, _skill):
        captured["sources"] = sources
        return {"answer": "It is three years [1].", "citations": [1], "proposal": None}

    monkeypatch.setattr(AssistantService, "_xai", fake_xai)
    thread = AssistantService().ensure_workspace(actor)
    result = AssistantService().ask(actor, thread["id"], "What is the confidentiality term?", contract_id=own["id"])
    assert result["messages"][-1]["content"] == "It is three years [1]."
    assert all(source["contract_id"] == own["id"] for source in captured["sources"])
    assert "ninety-nine" not in json.dumps(captured["sources"])


def test_confirmed_assistant_action_uses_service_permission_boundary(workspace, fresh_db):
    actor, _, _ = workspace
    contract = ContractService().create(actor, {"title": "Service agreement", "reference": "SVC-1"})
    thread = AssistantService().ensure_workspace(actor)
    message_id, action_id, created = new_id(), new_id(), now()
    with fresh_db.transaction() as tx:
        tx.execute(
            "INSERT INTO assistant_messages(id,organisation_id,thread_id,user_id,role,content,created_at) VALUES (?,?,?,?,?,?,?)",
            (message_id, actor.organisation_id, thread["id"], actor.user_id, "assistant", "I can add that obligation.", created),
        )
        tx.execute(
            "INSERT INTO assistant_actions(id,organisation_id,thread_id,message_id,tool_name,summary,arguments_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (action_id, actor.organisation_id, thread["id"], message_id, "add_obligation", "Add annual review", json.dumps({"contract_id": contract["id"], "title": "Annual review", "due_date": "2027-09-07", "recurrence": "annual"}), created),
        )
    AssistantService().decide(actor, action_id, True)
    assert fresh_db.one("SELECT status FROM assistant_actions WHERE id=?", (action_id,))["status"] == "confirmed"
    assert fresh_db.one("SELECT title FROM obligations WHERE contract_id=?", (contract["id"],))["title"] == "Annual review"
