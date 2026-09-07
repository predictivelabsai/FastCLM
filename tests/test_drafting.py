from __future__ import annotations

from fastclm.services.contracts import ContractService
from fastclm.services.drafting import DraftingService
from fastclm.services.identity import IdentityService, now


def test_clause_insertion_and_redline_decision_create_immutable_versions(workspace):
    actor, _, _ = workspace
    contracts, drafting = ContractService(), DraftingService()
    contract = contracts.create(actor, {"title": "Negotiated agreement"})
    clause = contracts.clauses(actor)[0]
    drafting.insert_clause(actor, contract["id"], clause["id"])
    block = contracts.get(actor, contract["id"])["blocks"][-1]
    redline = drafting.propose_redline(actor, contract["id"], "replace", block["content"] + " Agreed exception.", "Counterparty request", block["id"])
    assert "--- Current" in drafting.workspace(actor, contract["id"])["redlines"][0]["diff"]
    drafting.decide_redline(actor, redline["id"], True)
    item = contracts.get(actor, contract["id"])
    assert item["versions"][0]["label"] == "Accepted redline"
    assert "Agreed exception" in item["blocks"][-1]["content"]
    assert drafting.workspace(actor, contract["id"])["redlines"][0]["status"] == "accepted"


def test_comments_mentions_and_assignments_are_tenant_scoped(workspace, fresh_db):
    actor, _, organisation = workspace
    member, _ = IdentityService().create_workspace("collaborator@example.test", "Secure-collab-pass1!", "Collaborator", "Other org")
    with fresh_db.transaction() as tx:
        tx.execute("INSERT INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,?,?)", (organisation["id"], member["id"], "member", now()))
    contract = ContractService().create(actor, {"title": "Review agreement"})
    drafting = DraftingService()
    comment = drafting.add_comment(actor, contract["id"], "Please check the liability cap.", mention_user_ids=[member["id"]])
    assignment = drafting.assign(actor, contract["id"], "Review liability", member["id"], "2026-10-01", comment_id=comment["id"])
    member_actor = IdentityService().actor(member["id"], organisation["id"])
    assert drafting.complete_assignment(member_actor, assignment["id"])["status"] == "complete"
    assert drafting.resolve_comment(actor, comment["id"])["status"] == "resolved"
    assert fresh_db.scalar("SELECT COUNT(*) FROM comment_mentions WHERE comment_id=?", (comment["id"],)) == 1


def test_template_assembly_and_preferred_fallback_playbook(workspace):
    actor, _, _ = workspace
    drafting, contracts = DraftingService(), ContractService()
    template = drafting.create_template(actor, {
        "name": "Services starter", "contract_type": "Master services agreement", "jurisdiction": "England and Wales",
        "blocks": [{"block_type": "heading", "content": "Services Agreement"}, {"block_type": "paragraph", "content": "The parties agree as follows."}],
    })
    assembled = drafting.assemble_template(actor, template["id"], {"title": "New services agreement", "reference": "TPL-1"})
    assert assembled["contract_type"] == "Master services agreement"
    assert assembled["blocks"][0]["content"] == "Services Agreement"
    clause = next(item for item in contracts.clauses(actor) if item["fallback_body"])
    playbook = drafting.create_playbook(actor, {"name": "Fallback positions", "clause_ids": [clause["id"]]})
    inserted = drafting.apply_playbook(actor, assembled["id"], playbook["id"], use_fallback=True)
    assert inserted[0]["content"] == clause["fallback_body"]
