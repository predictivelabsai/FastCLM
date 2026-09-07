from datetime import date, timedelta

import pytest

from fastclm.security import Actor
from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService
from fastclm.services.review import ReviewService


def create_contract(service, actor, title="Test agreement"):
    return service.create(actor, {"title": title, "value_amount": "1200.50", "currency": "GBP"})


def test_contract_versions_are_immutable_and_checksums_change(workspace):
    actor, _, _ = workspace
    service = ContractService()
    contract = create_contract(service, actor)
    first = service.get(actor, contract["id"])["versions"][0]
    service.add_block(actor, contract["id"], "clause", "This agreement is governed by English law and may be terminated on notice.")
    second = service.snapshot(actor, contract["id"], "Legal draft")
    versions = service.get(actor, contract["id"])["versions"]
    assert [item["version_number"] for item in versions] == [2, 1]
    assert first["checksum"] != second["checksum"]
    assert "terminated" not in first["body_text"]


def test_contract_transition_requires_recorded_approval(workspace):
    actor, _, _ = workspace
    service = ContractService()
    contract = create_contract(service, actor)
    service.transition(actor, contract["id"], "review")
    service.transition(actor, contract["id"], "approval")
    with pytest.raises(ValueError):
        service.transition(actor, contract["id"], "signature")
    service.approve(actor, contract["id"], "approved", "Approved")
    assert service.get(actor, contract["id"])["status"] == "signature"
    service.transition(actor, contract["id"], "active")
    assert service.get(actor, contract["id"])["status"] == "active"


def test_tenant_isolation_applies_to_contracts_and_counterparties(workspace):
    actor, _, _ = workspace
    service = ContractService()
    contract = create_contract(service, actor, "Private agreement")
    identity = IdentityService()
    other_user, other_org = identity.create_workspace("other@example.test", "Another-secure-pass1!", "Other", "Other Company")
    other_actor = identity.actor(other_user["id"], other_org["id"])
    assert service.list(other_actor) == []
    with pytest.raises(LookupError):
        service.get(other_actor, contract["id"])


def test_decimal_validation_and_dashboard_deadlines(workspace):
    actor, _, _ = workspace
    service = ContractService()
    with pytest.raises(ValueError):
        service.create(actor, {"title": "Bad value", "value_amount": "12.3.4"})
    contract = create_contract(service, actor)
    service.add_obligation(actor, contract["id"], {"title": "Past due", "due_date": (date.today() - timedelta(days=1)).isoformat()})
    assert service.dashboard(actor)["overdue"] == 1


def test_role_permissions_are_enforced_at_service_boundary(workspace):
    actor, _, organisation = workspace
    member = Actor("member", "member@example.test", "Member", organisation["id"], organisation["name"], "approver")
    with pytest.raises(PermissionError):
        ContractService().create(member, {"title": "Not allowed"})


def test_deterministic_review_is_non_authoritative(workspace):
    actor, _, _ = workspace
    service = ContractService()
    contract = create_contract(service, actor)
    service.add_block(actor, contract["id"], "clause", "This agreement automatically renews and has unlimited liability.")
    result = ReviewService().review(actor, contract["id"])
    assert result["risk_level"] == "high"
    assert service.get(actor, contract["id"])["status"] == "draft"
    assert any(item["title"] == "Automatic renewal" for item in result["findings"])
