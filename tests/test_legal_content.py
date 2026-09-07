from __future__ import annotations

import pytest

from fastclm.security import Actor
from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService
from fastclm.services.legal_content import LegalContentService


def test_qualified_counsel_review_requires_attestation_and_preserves_evidence(workspace, fresh_db):
    actor, _, _ = workspace
    clause = ContractService().clauses(actor)[0]
    service = LegalContentService()
    request = service.request_review(actor, {
        "scope": "Review the exact preferred and fallback wording",
        "jurisdiction": "England and Wales",
        "clause_ids": [clause["id"]],
        "reviewer_name": "Alex Counsel",
        "reviewer_email": "alex@law.example",
    })
    filename, review_pack = service.review_pack(actor, request["id"])
    assert filename.endswith(".md")
    assert clause["body"] in review_pack
    assert "Wording checksum" in review_pack
    assert "approved, changes requested, or not approved" in review_pack
    payload = {
        "clause_id": clause["id"], "request_id": request["id"], "decision": "approved",
        "reviewed_jurisdiction": "England and Wales", "reviewer_name": "Alex Counsel",
        "reviewer_organisation": "Example Law LLP", "reviewer_qualification": "Solicitor, SRA 123456",
        "evidence_reference": "matter://example-law/CLM-001", "notes": "Approved for the stated scope only.",
    }
    with pytest.raises(ValueError, match="qualified"):
        service.record_review(actor, payload)
    payload["qualification_attested"] = "true"
    review = service.record_review(actor, payload)
    assert review["qualification_attested"] == 1
    overview = service.overview(actor)
    reviewed = next(item for item in overview["clauses"] if item["id"] == clause["id"])
    assert reviewed["legal_review_status"] == "approved"
    assert next(item for item in overview["requests"] if item["id"] == request["id"])["status"] == "completed"
    assert fresh_db.scalar("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'legal_content.%'") == 2
    with fresh_db.transaction() as tx:
        tx.execute("UPDATE clauses SET risk_guidance=? WHERE id=? AND organisation_id=?", ("Changed guidance", clause["id"], actor.organisation_id))
    changed = next(item for item in service.overview(actor)["clauses"] if item["id"] == clause["id"])
    assert changed["legal_review_status"] == "stale"


def test_legal_review_is_tenant_scoped_and_requires_clause_manager(workspace):
    actor, _, organisation = workspace
    clause = ContractService().clauses(actor)[0]
    service = LegalContentService()
    member = Actor("member", "member@example.test", "Member", organisation["id"], organisation["name"], "member")
    with pytest.raises(PermissionError):
        service.request_review(member, {"scope": "Review", "jurisdiction": "England", "clause_ids": [clause["id"]]})
    other_user, other_org = IdentityService().create_workspace(
        "legal-other@example.test", "Another-secure-pass1!", "Other", "Other Legal Studio"
    )
    other_actor = IdentityService().actor(other_user["id"], other_org["id"])
    request = service.request_review(actor, {"scope": "Review", "jurisdiction": "England", "clause_ids": [clause["id"]]})
    with pytest.raises(LookupError):
        service.review_pack(other_actor, request["id"])
    with pytest.raises(LookupError):
        service.request_review(other_actor, {"scope": "Review", "jurisdiction": "England", "clause_ids": [clause["id"]]})
