from __future__ import annotations

import json

import pytest

from fastclm.services.assistant import TOOL_DEFINITIONS, WRITE_TOOLS, AssistantService, find_quote_anchor, verify_word_citations
from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService, new_id, now
from fastclm.services.legal_content import LegalContentService
from fastclm.services.skills import SkillService


def test_cockpit_and_skills_are_tenant_scoped_and_versioned(workspace):
    actor, _, _ = workspace
    cockpit = AssistantService().cockpit(actor)
    assert cockpit["messages"][0]["role"] == "assistant"
    assert len(cockpit["skills"]) == 5

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

    def fake_stream(_self, _key, _question, sources, _skill, _history):
        captured["sources"] = sources
        yield {"type": "token", "text": "It is three years [[cite:1|three years]]."}

    monkeypatch.setattr(AssistantService, "_xai_stream", fake_stream)
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


def test_assistant_tool_catalog_covers_contract_and_governance_workflows(workspace, fresh_db):
    actor, _, _ = workspace
    names = {item["function"]["name"] for item in TOOL_DEFINITIONS}
    assert names == WRITE_TOOLS
    assert {
        "add_counterparty", "prepare_signature_request", "create_workspace_backup",
        "set_reminder_preferences", "create_reminder_escalation", "update_notification_template",
        "create_approval_policy", "create_approval_delegation", "set_retention_policy",
    } <= names
    assert not {"approve_contract", "record_approval_decision", "dispatch_signature_request", "change_member_role"} & names
    thread = AssistantService().ensure_workspace(actor)
    message_id, created = new_id(), now()
    actions = [
        (new_id(), "add_counterparty", {"name": "Assistant Counterparty Ltd", "jurisdiction": "England and Wales"}),
        (new_id(), "set_reminder_preferences", {"enabled": True, "due_soon_days": 21, "overdue_repeat_days": 3}),
        (new_id(), "set_retention_policy", {"enabled": True, "days": 730}),
        (new_id(), "create_approval_policy", {"name": "Assistant policy", "stages": [{"name": "Legal", "allowed_roles": ["owner"], "required_approvals": 1, "allow_requester": False, "require_distinct_prior": False}]}),
    ]
    with fresh_db.transaction() as tx:
        tx.execute(
            "INSERT INTO assistant_messages(id,organisation_id,thread_id,user_id,role,content,created_at) VALUES (?,?,?,?,?,?,?)",
            (message_id, actor.organisation_id, thread["id"], actor.user_id, "assistant", "Governance proposals", created),
        )
        for action_id, tool_name, arguments in actions:
            tx.execute(
                "INSERT INTO assistant_actions(id,organisation_id,thread_id,message_id,tool_name,summary,arguments_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (action_id, actor.organisation_id, thread["id"], message_id, tool_name, tool_name, json.dumps(arguments), created),
            )
    for action_id, _tool_name, _arguments in actions:
        AssistantService().decide(actor, action_id, True)
    assert fresh_db.scalar("SELECT COUNT(*) FROM counterparties WHERE organisation_id=? AND name='Assistant Counterparty Ltd'", (actor.organisation_id,)) == 1
    assert fresh_db.one("SELECT due_soon_days,overdue_repeat_days FROM reminder_preferences WHERE organisation_id=? AND user_id=?", (actor.organisation_id, actor.user_id)) == {"due_soon_days": 21, "overdue_repeat_days": 3}
    assert fresh_db.one("SELECT retention_enabled,retention_days FROM organisations WHERE id=?", (actor.organisation_id,)) == {"retention_enabled": 1, "retention_days": 730}
    assert fresh_db.scalar("SELECT COUNT(*) FROM approval_policies WHERE organisation_id=? AND name='Assistant policy'", (actor.organisation_id,)) == 1


def test_word_level_citations_require_consecutive_source_words():
    source = {
        "contract_id": "contract-1", "version_id": "version-1", "title": "NDA", "reference": "NDA-1",
        "version_number": 2, "source_filename": "nda.pdf", "media_type": "application/pdf",
        "body_text": "Confidential Information must be protected using reasonable care for three years.",
    }
    answer, citations = verify_word_citations(
        "The duty lasts three years [[cite:1|for three years]]. A different claim [[cite:1|for ninety years]].",
        [source],
    )
    assert answer == "The duty lasts three years [1]. A different claim [1 · unverified]."
    assert citations[0]["verified"] is True
    assert citations[0]["verification_method"] == "consecutive_word_match"
    assert citations[0]["verification_confidence"] == 1.0
    assert citations[0]["word_count"] == 3
    assert citations[0]["start_word"] == 8
    assert citations[1]["verified"] is False
    assert citations[1]["verification_method"] == "failed"


def test_word_verification_handles_pdf_hyphenation_and_unicode_ligatures():
    source = {
        "contract_id": "contract-1", "version_id": "version-1", "title": "Terms", "reference": "T-1",
        "version_number": 1, "source_filename": "terms.pdf", "media_type": "application/pdf",
        "body_text": "The oﬃcial thirty-\nday notice period applies.",
    }
    answer, citations = verify_word_citations(
        "Notice is required [[cite:1|official thirty-day notice period]].",
        [source],
    )
    assert answer == "Notice is required [1]."
    assert citations[0]["verified"] is True
    assert citations[0]["word_count"] == 5
    assert source["body_text"][citations[0]["start_char"]:citations[0]["end_char"]] == "oﬃcial thirty-\nday notice period"


def test_verified_citation_has_exact_character_and_page_anchor():
    body = "Page one confidentiality.\n\nPage two says termination requires thirty days notice."
    anchor = find_quote_anchor(
        "termination requires thirty days notice",
        body,
        ["Page one confidentiality.", "Page two says termination requires thirty days notice."],
    )
    assert anchor["page"] == 2
    assert body[anchor["start_char"]:anchor["end_char"]] == "termination requires thirty days notice"
    assert anchor["start_word"] == 6
    assert anchor["end_word"] == 10


def test_stream_persists_tokens_tool_receipts_and_verified_citation(workspace, monkeypatch):
    actor, _, _ = workspace
    contract = ContractService().create(actor, {"title": "Streaming NDA", "reference": "STREAM-1"})
    ContractService().add_block(actor, contract["id"], "clause", "Confidential information is protected for three years.")
    ContractService().snapshot(actor, contract["id"], "Review copy")
    monkeypatch.setattr("fastclm.services.assistant.authorize", lambda _user_id: ("key", "byok", False))

    def fake_stream(_self, _key, _question, _sources, _skill, _history):
        yield {"type": "token", "text": "The term is three years "}
        yield {"type": "token", "text": "[[cite:1|for three years]]."}

    monkeypatch.setattr(AssistantService, "_xai_stream", fake_stream)
    thread = AssistantService().ensure_workspace(actor)
    events = list(AssistantService().stream(actor, thread["id"], "What is the confidentiality term?", contract_id=contract["id"]))
    assert any(item["type"] == "token" for item in events)
    assert events[-1]["type"] == "complete"
    result = AssistantService().cockpit(actor, thread["id"])["messages"][-1]
    assert result["content"] == "The term is three years [1]."
    assert result["citations"][0]["verified"] is True
    assert {item["tool"] for item in result["tool_runs"]} == {"search_contracts", "xai", "verify_citations"}


def test_conversation_can_propose_and_confirm_a_new_skill(workspace, monkeypatch):
    actor, _, _ = workspace
    monkeypatch.setattr("fastclm.services.assistant.authorize", lambda _user_id: ("key", "byok", False))
    seen = {}

    def fake_stream(_self, _key, _question, _sources, skill, _history):
        seen["skill"] = skill["slug"]
        yield {"type": "token", "text": "I have enough detail to prepare that skill."}
        yield {"type": "tool_start", "name": "create_skill"}
        yield {"type": "tool_call", "name": "create_skill", "arguments": {
            "name": "Board Minutes Review", "description": "Use when reviewing draft board minutes.",
            "jurisdiction": "UK", "instructions": "# Board Minutes Review\n\nCheck attendees, resolutions, conflicts, and actions.\n",
        }}

    monkeypatch.setattr(AssistantService, "_xai_stream", fake_stream)
    thread = AssistantService().ensure_workspace(actor)
    list(AssistantService().stream(actor, thread["id"], "Create a skill for reviewing board minutes"))
    action = AssistantService().cockpit(actor, thread["id"])["messages"][-1]["actions"][0]
    assert seen["skill"] == "skill-creator"
    assert action["tool_name"] == "create_skill"
    AssistantService().decide(actor, action["id"], True)
    assert SkillService().by_slug(actor, "board-minutes-review")["current_version"] == 1


def test_conversation_can_propose_scoped_counsel_review_without_claiming_approval(workspace, monkeypatch):
    actor, _, _ = workspace
    clause = ContractService().clauses(actor)[0]
    monkeypatch.setattr("fastclm.services.assistant.authorize", lambda _user_id: ("key", "byok", False))

    def fake_stream(_self, _key, _question, _sources, _skill, history):
        assert clause["id"] in history[-1]["content"]
        assert '"legal_review_status": "unreviewed"' in history[-1]["content"]
        yield {"type": "token", "text": "I can prepare a scoped request; this does not approve the clause."}
        yield {"type": "tool_start", "name": "request_legal_review"}
        yield {"type": "tool_call", "name": "request_legal_review", "arguments": {
            "scope": "Review preferred and fallback wording for SME service agreements.",
            "jurisdiction": "England and Wales", "clause_ids": [clause["id"]],
            "reviewer_name": "", "reviewer_email": "",
        }}

    monkeypatch.setattr(AssistantService, "_xai_stream", fake_stream)
    thread = AssistantService().ensure_workspace(actor)
    list(AssistantService().stream(actor, thread["id"], "Ask counsel to review our first clause"))
    action = AssistantService().cockpit(actor, thread["id"])["messages"][-1]["actions"][0]
    assert action["tool_name"] == "request_legal_review"
    AssistantService().decide(actor, action["id"], True)
    overview = LegalContentService().overview(actor)
    assert overview["requests"][0]["status"] == "open"
    assert overview["counts"]["approved"] == 0


def test_confirmed_matter_memory_scopes_multi_contract_retrieval(workspace):
    actor, _, _ = workspace
    service = ContractService()
    contracts = []
    for reference, title in (("M-1", "Framework"), ("M-2", "Statement of work"), ("OUT", "Unrelated lease")):
        contract = service.create(actor, {"title": title, "reference": reference})
        service.add_block(actor, contract["id"], "clause", f"{title} contains shared programme terms.")
        service.snapshot(actor, contract["id"], "Matter source")
        contracts.append(contract)
    thread = AssistantService().new_thread(actor, "Cloud programme")
    AssistantService().set_matter_context(actor, thread["id"], [contracts[0]["id"], contracts[1]["id"]], "Framework and SOW for the cloud programme.")
    sources = AssistantService()._sources(actor, "programme terms", thread_id=thread["id"])
    assert {item["contract_id"] for item in sources} == {contracts[0]["id"], contracts[1]["id"]}
    cockpit = AssistantService().cockpit(actor, thread["id"])
    assert cockpit["thread"]["memory_summary"] == "Framework and SOW for the cloud programme."
    assert len(cockpit["matter_contracts"]) == 2


def test_confirmed_conversational_skill_test_and_revision_are_attributable(workspace, fresh_db):
    actor, _, _ = workspace
    cockpit = AssistantService().cockpit(actor)
    skill = cockpit["skills"][0]
    contract = ContractService().create(actor, {"title": "Example NDA", "reference": "TEST-1"})
    thread = cockpit["thread"]
    message_id, created = new_id(), now()
    with fresh_db.transaction() as tx:
        tx.execute(
            "INSERT INTO assistant_messages(id,organisation_id,thread_id,user_id,role,content,created_at) VALUES (?,?,?,?,?,?,?)",
            (message_id, actor.organisation_id, thread["id"], actor.user_id, "assistant", "The example is ready for review.", created),
        )
        test_action, revision_action = new_id(), new_id()
        tx.execute(
            "INSERT INTO assistant_actions(id,organisation_id,thread_id,message_id,tool_name,summary,arguments_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (test_action, actor.organisation_id, thread["id"], message_id, "record_skill_test", "Record passing test", json.dumps({"skill_id": skill["id"], "contract_id": contract["id"], "prompt": "Identify the term", "expected_outcome": "Cite the term", "observed_output": "The term was cited.", "verdict": "pass"}), created),
        )
        tx.execute(
            "INSERT INTO assistant_actions(id,organisation_id,thread_id,message_id,tool_name,summary,arguments_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (revision_action, actor.organisation_id, thread["id"], message_id, "revise_skill", "Refine output", json.dumps({"skill_id": skill["id"], "name": skill["name"], "description": skill["description"], "jurisdiction": skill["jurisdiction"], "instructions": skill["instructions"] + "\nAlways state the tested outcome.\n"}), created),
        )
    AssistantService().decide(actor, test_action, True)
    AssistantService().decide(actor, revision_action, True)
    updated = SkillService().get(actor, skill["id"])
    assert updated["current_version"] == 2
    assert updated["tests"][0]["verdict"] == "pass"
    assert updated["tests"][0]["skill_version"] == 1
