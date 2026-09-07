from datetime import datetime, timedelta, timezone

import pytest

from fastclm.security import Actor
from fastclm.services.approvals import ApprovalService
from fastclm.services.contracts import ContractService
from fastclm.services.identity import new_id, now


def add_member(database, organisation, name, role):
    user_id = new_id()
    with database.transaction() as tx:
        tx.execute(
            "INSERT INTO users(id,email,name,password_hash,created_at,is_verified) VALUES (?,?,?,?,?,1)",
            (user_id, f"{name.lower()}@example.test", name, None, now()),
        )
        tx.execute(
            "INSERT INTO memberships(organisation_id,user_id,role,created_at) VALUES (?,?,?,?)",
            (organisation["id"], user_id, role, now()),
        )
    return Actor(user_id, f"{name.lower()}@example.test", name, organisation["id"], organisation["name"], role)


def approval_contract(actor):
    contracts = ContractService()
    contract = contracts.create(actor, {"title": "Approval orchestration agreement"})
    contracts.transition(actor, contract["id"], "review")
    return contracts, contract


def test_multi_stage_policy_enforces_separation_of_duties(workspace, fresh_db):
    owner, _, organisation = workspace
    approver = add_member(fresh_db, organisation, "Approver", "approver")
    approvals = ApprovalService()
    policy = approvals.create_policy(owner, {
        "name": "Two-stage legal and commercial",
        "contract_type": "Commercial agreement",
        "stages": [
            {"name": "Legal review", "allowed_roles": ["owner"], "required_approvals": 1},
            {"name": "Commercial approval", "allowed_roles": ["owner", "approver"], "required_approvals": 1, "require_distinct_prior": True},
        ],
    })
    contracts, contract = approval_contract(owner)
    contracts.transition(owner, contract["id"], "approval")
    workspace_data = approvals.workspace(owner, contract["id"])
    assert workspace_data["run"]["policy_id"] == policy["id"]

    approvals.decide(owner, workspace_data["run"]["id"], "approved", "Legal terms accepted")
    assert approvals.workspace(owner, contract["id"])["run"]["current_stage_position"] == 2
    with pytest.raises(PermissionError, match="Separation of duties"):
        approvals.decide(owner, workspace_data["run"]["id"], "approved")
    approvals.decide(approver, workspace_data["run"]["id"], "approved", "Commercial terms accepted")

    assert contracts.get(owner, contract["id"])["status"] == "signature"
    assert approvals.workspace(owner, contract["id"])["run"]["status"] == "approved"
    assert fresh_db.scalar("SELECT COUNT(*) FROM approvals WHERE contract_id=?", (contract["id"],)) == 1


def test_quorum_and_requester_exclusion(workspace, fresh_db):
    owner, _, organisation = workspace
    first = add_member(fresh_db, organisation, "First", "approver")
    second = add_member(fresh_db, organisation, "Second", "approver")
    approvals = ApprovalService()
    approvals.create_policy(owner, {
        "name": "Two-person quorum",
        "contract_type": "Commercial agreement",
        "stages": [{
            "name": "Independent approval",
            "allowed_roles": ["owner", "approver"],
            "required_approvals": 2,
            "allow_requester": False,
        }],
    })
    contracts, contract = approval_contract(owner)
    contracts.transition(owner, contract["id"], "approval")
    run = approvals.workspace(owner, contract["id"])["run"]

    with pytest.raises(PermissionError, match="requester"):
        approvals.decide(owner, run["id"], "approved")
    approvals.decide(first, run["id"], "approved")
    assert contracts.get(owner, contract["id"])["status"] == "approval"
    approvals.decide(second, run["id"], "approved")
    assert contracts.get(owner, contract["id"])["status"] == "signature"


def test_time_bounded_delegation_honours_explicit_assignment(workspace, fresh_db):
    owner, _, organisation = workspace
    delegator = add_member(fresh_db, organisation, "Delegator", "approver")
    delegate = add_member(fresh_db, organisation, "Delegate", "approver")
    approvals = ApprovalService()
    approvals.create_policy(owner, {
        "name": "Assigned approver",
        "contract_type": "Commercial agreement",
        "stages": [{"name": "Named approval", "allowed_roles": ["approver"], "required_approvals": 1}],
    })
    contracts, contract = approval_contract(owner)
    contracts.transition(owner, contract["id"], "approval")
    workspace_data = approvals.workspace(owner, contract["id"])
    run, stage = workspace_data["run"], workspace_data["stages"][0]
    approvals.assign(owner, run["id"], stage["id"], delegator.user_id)

    with pytest.raises(PermissionError, match="not eligible"):
        approvals.decide(delegate, run["id"], "approved")
    current = datetime.now(timezone.utc)
    approvals.delegate(
        delegator,
        delegate.user_id,
        (current - timedelta(minutes=5)).isoformat(),
        (current + timedelta(days=1)).isoformat(),
    )
    decision = approvals.decide(delegate, run["id"], "approved", "Acting during leave")
    assert decision["actor_user_id"] == delegate.user_id
    assert decision["represented_user_id"] == delegator.user_id
    assert contracts.get(owner, contract["id"])["status"] == "signature"
