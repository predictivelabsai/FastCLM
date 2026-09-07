"""Ordered, human-controlled approval workflows."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastclm.database import get_database
from fastclm.lifecycle import require_transition
from fastclm.security import Actor, PERMISSIONS
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now


APPROVER_ROLES = frozenset(role for role, permissions in PERMISSIONS.items() if "contracts.approve" in permissions)


class ApprovalService:
    def _contract(self, actor: Actor, contract_id: str) -> dict:
        row = get_database().one(
            "SELECT * FROM contracts WHERE id=? AND organisation_id=?",
            (contract_id, actor.organisation_id),
        )
        if not row:
            raise LookupError("Contract not found")
        return row

    def _run(self, actor: Actor, run_id: str) -> dict:
        row = get_database().one(
            "SELECT r.*,p.name policy_name FROM contract_approval_runs r "
            "JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE r.id=? AND r.organisation_id=?",
            (run_id, actor.organisation_id),
        )
        if not row:
            raise LookupError("Approval run not found")
        return row

    def ensure_default_policy(self, actor: Actor) -> dict:
        db = get_database()
        existing = db.one(
            "SELECT * FROM approval_policies WHERE organisation_id=? AND name='Standard approval'",
            (actor.organisation_id,),
        )
        if existing:
            return existing
        policy_id, stage_id, created = new_id(), new_id(), now()
        with db.transaction() as tx:
            existing = tx.one(
                "SELECT * FROM approval_policies WHERE organisation_id=? AND name='Standard approval'",
                (actor.organisation_id,),
            )
            if existing:
                return existing
            tx.execute(
                "INSERT INTO approval_policies(id,organisation_id,name,contract_type,active,created_by,created_at,updated_at) "
                "VALUES (?,?,?,?,1,?,?,?)",
                (policy_id, actor.organisation_id, "Standard approval", "", actor.user_id, created, created),
            )
            tx.execute(
                "INSERT INTO approval_policy_stages(id,organisation_id,policy_id,position,name,allowed_roles_json,required_approvals,allow_requester,require_distinct_prior,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (stage_id, actor.organisation_id, policy_id, 1, "Approval", json.dumps(sorted(APPROVER_ROLES)), 1, 1, 0, created),
            )
            AuditService().record(actor, "approval_policy", policy_id, "approval.policy.defaulted", {}, tx)
        return db.one("SELECT * FROM approval_policies WHERE id=?", (policy_id,))

    def create_policy(self, actor: Actor, data: dict) -> dict:
        actor.require("team.manage")
        name = str(data.get("name", "")).strip()
        stages = list(data.get("stages") or [])
        if not name:
            raise ValueError("Policy name is required")
        if not 1 <= len(stages) <= 10:
            raise ValueError("A policy requires between 1 and 10 stages")
        clean_stages = []
        for position, stage in enumerate(stages, 1):
            stage_name = str(stage.get("name", "")).strip() or f"Stage {position}"
            roles = sorted({str(role).strip().lower() for role in stage.get("allowed_roles", [])})
            if not roles or any(role not in APPROVER_ROLES for role in roles):
                raise ValueError("Every stage must use an approval-capable role")
            try:
                quorum = int(stage.get("required_approvals", 1))
            except (TypeError, ValueError) as exc:
                raise ValueError("Required approvals must be a whole number") from exc
            if quorum < 1:
                raise ValueError("Required approvals must be at least one")
            clean_stages.append((stage_name, roles, quorum, bool(stage.get("allow_requester", True)), bool(stage.get("require_distinct_prior", False))))
        policy_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO approval_policies(id,organisation_id,name,contract_type,active,created_by,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?)",
                (policy_id, actor.organisation_id, name, str(data.get("contract_type", "")).strip(), actor.user_id, created, created),
            )
            for position, (stage_name, roles, quorum, allow_requester, distinct) in enumerate(clean_stages, 1):
                tx.execute(
                    "INSERT INTO approval_policy_stages(id,organisation_id,policy_id,position,name,allowed_roles_json,required_approvals,allow_requester,require_distinct_prior,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), actor.organisation_id, policy_id, position, stage_name, json.dumps(roles), quorum, int(allow_requester), int(distinct), created),
                )
            AuditService().record(actor, "approval_policy", policy_id, "approval.policy.created", {"name": name, "stages": len(clean_stages)}, tx)
        return self.policy(actor, policy_id)

    def policy(self, actor: Actor, policy_id: str) -> dict:
        actor.require("contracts.view")
        row = get_database().one(
            "SELECT * FROM approval_policies WHERE id=? AND organisation_id=?",
            (policy_id, actor.organisation_id),
        )
        if not row:
            raise LookupError("Approval policy not found")
        row["stages"] = get_database().rows(
            "SELECT * FROM approval_policy_stages WHERE policy_id=? AND organisation_id=? ORDER BY position",
            (policy_id, actor.organisation_id),
        )
        for stage in row["stages"]:
            stage["allowed_roles"] = json.loads(stage["allowed_roles_json"])
        return row

    def policies(self, actor: Actor) -> list[dict]:
        actor.require("contracts.view")
        rows = get_database().rows(
            "SELECT p.*,(SELECT COUNT(*) FROM approval_policy_stages s WHERE s.policy_id=p.id) stage_count "
            "FROM approval_policies p WHERE p.organisation_id=? ORDER BY p.active DESC,p.name",
            (actor.organisation_id,),
        )
        return rows

    def overview(self, actor: Actor) -> dict:
        actor.require("contracts.view")
        db = get_database()
        policies = self.policies(actor)
        for policy in policies:
            policy["stages"] = db.rows(
                "SELECT * FROM approval_policy_stages WHERE policy_id=? AND organisation_id=? ORDER BY position",
                (policy["id"], actor.organisation_id),
            )
            for stage in policy["stages"]:
                stage["allowed_roles"] = json.loads(stage["allowed_roles_json"])
        return {
            "policies": policies,
            "members": db.rows(
                "SELECT m.user_id,m.role,u.name,u.email FROM memberships m JOIN users u ON u.id=m.user_id "
                "WHERE m.organisation_id=? ORDER BY u.name",
                (actor.organisation_id,),
            ),
            "delegations": db.rows(
                "SELECT d.*,a.name delegator_name,b.name delegate_name FROM approval_delegations d "
                "JOIN users a ON a.id=d.delegator_user_id JOIN users b ON b.id=d.delegate_user_id "
                "WHERE d.organisation_id=? ORDER BY d.created_at DESC",
                (actor.organisation_id,),
            ),
        }

    def ensure_run(self, actor: Actor, contract_id: str, policy_id: str = "") -> dict:
        contract = self._contract(actor, contract_id)
        if contract["status"] != "approval":
            raise ValueError("Contract is not awaiting approval")
        active = get_database().one(
            "SELECT * FROM contract_approval_runs WHERE contract_id=? AND organisation_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
            (contract_id, actor.organisation_id),
        )
        if active:
            return active
        if policy_id:
            policy = get_database().one(
                "SELECT * FROM approval_policies WHERE id=? AND organisation_id=? AND active=1",
                (policy_id, actor.organisation_id),
            )
        else:
            policy = get_database().one(
                "SELECT * FROM approval_policies WHERE organisation_id=? AND active=1 AND contract_type=? ORDER BY created_at LIMIT 1",
                (actor.organisation_id, contract["contract_type"]),
            )
            policy = policy or get_database().one(
                "SELECT * FROM approval_policies WHERE organisation_id=? AND active=1 AND contract_type='' ORDER BY created_at LIMIT 1",
                (actor.organisation_id,),
            )
        policy = policy or self.ensure_default_policy(actor)
        if not policy:
            raise LookupError("Approval policy not found")
        run_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO contract_approval_runs(id,organisation_id,contract_id,policy_id,status,current_stage_position,initiated_by,created_at,updated_at) VALUES (?,?,?,?, 'active',1,?,?,?)",
                (run_id, actor.organisation_id, contract_id, policy["id"], actor.user_id, created, created),
            )
            AuditService().record(actor, "contract", contract_id, "approval.run.started", {"run_id": run_id, "policy_id": policy["id"]}, tx)
        return get_database().one("SELECT * FROM contract_approval_runs WHERE id=?", (run_id,))

    def cancel_active(self, actor: Actor, contract_id: str) -> None:
        changed = now()
        with get_database().transaction() as tx:
            runs = tx.rows(
                "SELECT id FROM contract_approval_runs WHERE contract_id=? AND organisation_id=? AND status='active'",
                (contract_id, actor.organisation_id),
            )
            if not runs:
                return
            tx.execute(
                "UPDATE contract_approval_runs SET status='cancelled',updated_at=?,completed_at=? WHERE contract_id=? AND organisation_id=? AND status='active'",
                (changed, changed, contract_id, actor.organisation_id),
            )
            for run in runs:
                AuditService().record(actor, "approval_run", run["id"], "approval.run.cancelled", {"contract_id": contract_id}, tx)

    def assign(self, actor: Actor, run_id: str, stage_id: str, user_id: str) -> dict:
        actor.require("team.manage")
        run = self._run(actor, run_id)
        if run["status"] != "active":
            raise ValueError("Approval run is no longer active")
        stage = get_database().one(
            "SELECT * FROM approval_policy_stages WHERE id=? AND policy_id=? AND organisation_id=?",
            (stage_id, run["policy_id"], actor.organisation_id),
        )
        member = get_database().one(
            "SELECT role FROM memberships WHERE organisation_id=? AND user_id=?",
            (actor.organisation_id, user_id),
        )
        if not stage or not member:
            raise LookupError("Stage or member not found")
        if member["role"] not in json.loads(stage["allowed_roles_json"]):
            raise ValueError("Assignee does not have a role allowed for this stage")
        assignment_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO approval_stage_assignments(id,organisation_id,run_id,stage_id,user_id,assigned_by,created_at) VALUES (?,?,?,?,?,?,?)",
                (assignment_id, actor.organisation_id, run_id, stage_id, user_id, actor.user_id, created),
            )
            AuditService().record(actor, "approval_run", run_id, "approval.stage.assigned", {"stage_id": stage_id, "user_id": user_id}, tx)
        return get_database().one("SELECT * FROM approval_stage_assignments WHERE id=?", (assignment_id,))

    def delegate(self, actor: Actor, delegate_user_id: str, starts_at: str, ends_at: str, delegator_user_id: str = "") -> dict:
        delegator_user_id = delegator_user_id or actor.user_id
        if delegator_user_id != actor.user_id:
            actor.require("team.manage")
        elif not actor.can("contracts.approve"):
            raise PermissionError("Only an approver can delegate approval authority")
        if delegate_user_id == delegator_user_id:
            raise ValueError("Delegate must be a different person")
        try:
            start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Delegation dates must be valid ISO timestamps") from exc
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= start:
            raise ValueError("Delegation must end after it starts")
        db = get_database()
        members = db.scalar(
            "SELECT COUNT(*) FROM memberships WHERE organisation_id=? AND user_id IN (?,?)",
            (actor.organisation_id, delegator_user_id, delegate_user_id),
        )
        delegator_role = db.scalar(
            "SELECT role FROM memberships WHERE organisation_id=? AND user_id=?",
            (actor.organisation_id, delegator_user_id),
        )
        if members != 2 or delegator_role not in APPROVER_ROLES:
            raise ValueError("Delegator and delegate must be eligible workspace members")
        delegation_id, created = new_id(), now()
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO approval_delegations(id,organisation_id,delegator_user_id,delegate_user_id,starts_at,ends_at,active,created_by,created_at) VALUES (?,?,?,?,?,?,1,?,?)",
                (delegation_id, actor.organisation_id, delegator_user_id, delegate_user_id, start.isoformat(), end.isoformat(), actor.user_id, created),
            )
            AuditService().record(actor, "approval_delegation", delegation_id, "approval.delegation.created", {"delegator_user_id": delegator_user_id, "delegate_user_id": delegate_user_id, "starts_at": start.isoformat(), "ends_at": end.isoformat()}, tx)
        return db.one("SELECT * FROM approval_delegations WHERE id=?", (delegation_id,))

    def _represented_user(self, actor: Actor, run: dict, stage: dict) -> str:
        db = get_database()
        assignments = db.rows(
            "SELECT user_id FROM approval_stage_assignments WHERE run_id=? AND stage_id=? AND organisation_id=?",
            (run["id"], stage["id"], actor.organisation_id),
        )
        assigned = {row["user_id"] for row in assignments}
        allowed = set(json.loads(stage["allowed_roles_json"]))
        if (not assigned and actor.role in allowed) or actor.user_id in assigned:
            return actor.user_id
        current = now()
        delegated = db.rows(
            "SELECT d.delegator_user_id,m.role FROM approval_delegations d "
            "JOIN memberships m ON m.organisation_id=d.organisation_id AND m.user_id=d.delegator_user_id "
            "WHERE d.organisation_id=? AND d.delegate_user_id=? AND d.active=1 AND d.starts_at<=? AND d.ends_at>=? ORDER BY d.created_at",
            (actor.organisation_id, actor.user_id, current, current),
        )
        for row in delegated:
            if row["role"] in allowed and (not assigned or row["delegator_user_id"] in assigned):
                return row["delegator_user_id"]
        raise PermissionError("You are not eligible for the current approval stage")

    def decide(self, actor: Actor, run_id: str, decision: str, comment: str = "") -> dict:
        actor.require("contracts.approve")
        run = self._run(actor, run_id)
        if run["status"] != "active":
            raise ValueError("Approval run is no longer active")
        if decision not in {"approved", "changes_requested"}:
            raise ValueError("Unsupported approval decision")
        stage = get_database().one(
            "SELECT * FROM approval_policy_stages WHERE policy_id=? AND organisation_id=? AND position=?",
            (run["policy_id"], actor.organisation_id, run["current_stage_position"]),
        )
        if not stage:
            raise LookupError("Current approval stage not found")
        represented = self._represented_user(actor, run, stage)
        if not stage["allow_requester"] and (represented == run["initiated_by"] or actor.user_id == run["initiated_by"]):
            raise PermissionError("The approval requester cannot decide this stage")
        if stage["require_distinct_prior"] and get_database().scalar(
            "SELECT COUNT(*) FROM approval_stage_decisions d JOIN approval_policy_stages s ON s.id=d.stage_id "
            "WHERE d.run_id=? AND d.decision='approved' AND s.position<? AND (d.actor_user_id=? OR d.represented_user_id=? OR d.actor_user_id=? OR d.represented_user_id=?)",
            (run_id, stage["position"], actor.user_id, actor.user_id, represented, represented),
        ):
            raise PermissionError("Separation of duties requires a different approver")
        decision_id, decided = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO approval_stage_decisions(id,organisation_id,run_id,stage_id,actor_user_id,represented_user_id,decision,comment,decided_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (decision_id, actor.organisation_id, run_id, stage["id"], actor.user_id, represented, decision, comment.strip(), decided),
            )
            AuditService().record(actor, "approval_run", run_id, "approval.stage.decided", {"stage_id": stage["id"], "decision": decision, "represented_user_id": represented}, tx)
        if decision == "changes_requested":
            self._complete(actor, run, "changes_requested", comment)
        else:
            votes = int(get_database().scalar(
                "SELECT COUNT(*) FROM approval_stage_decisions WHERE run_id=? AND stage_id=? AND decision='approved'",
                (run_id, stage["id"]),
            ) or 0)
            if votes >= int(stage["required_approvals"]):
                next_stage = get_database().one(
                    "SELECT * FROM approval_policy_stages WHERE policy_id=? AND organisation_id=? AND position>? ORDER BY position LIMIT 1",
                    (run["policy_id"], actor.organisation_id, stage["position"]),
                )
                if next_stage:
                    with get_database().transaction() as tx:
                        tx.execute("UPDATE contract_approval_runs SET current_stage_position=?,updated_at=? WHERE id=? AND organisation_id=?", (next_stage["position"], decided, run_id, actor.organisation_id))
                        AuditService().record(actor, "approval_run", run_id, "approval.stage.advanced", {"from": stage["position"], "to": next_stage["position"]}, tx)
                else:
                    self._complete(actor, run, "approved", comment)
        return get_database().one("SELECT * FROM approval_stage_decisions WHERE id=?", (decision_id,))

    def _complete(self, actor: Actor, run: dict, outcome: str, comment: str) -> None:
        completed = now()
        legacy_id = new_id()
        target = "signature" if outcome == "approved" else "review"
        with get_database().transaction() as tx:
            contract = tx.one(
                "SELECT status FROM contracts WHERE id=? AND organisation_id=?",
                (run["contract_id"], actor.organisation_id),
            )
            if not contract:
                raise LookupError("Contract not found")
            require_transition(contract["status"], target)
            tx.execute(
                "UPDATE contract_approval_runs SET status=?,updated_at=?,completed_at=? WHERE id=? AND organisation_id=? AND status='active'",
                (outcome, completed, completed, run["id"], actor.organisation_id),
            )
            tx.execute(
                "INSERT INTO approvals(id,organisation_id,contract_id,approver_user_id,decision,comment,decided_at) VALUES (?,?,?,?,?,?,?)",
                (legacy_id, actor.organisation_id, run["contract_id"], actor.user_id, outcome, comment.strip(), completed),
            )
            tx.execute(
                "UPDATE contracts SET status=?,updated_at=? WHERE id=? AND organisation_id=?",
                (target, completed, run["contract_id"], actor.organisation_id),
            )
            AuditService().record(actor, "contract", run["contract_id"], "approval.run.completed", {"run_id": run["id"], "outcome": outcome}, tx)
            AuditService().record(actor, "contract", run["contract_id"], "contract.transitioned", {"from": contract["status"], "to": target, "approval_run_id": run["id"]}, tx)

    def decide_contract(self, actor: Actor, contract_id: str, decision: str, comment: str = "") -> dict:
        run = self.ensure_run(actor, contract_id)
        return self.decide(actor, run["id"], decision, comment)

    def workspace(self, actor: Actor, contract_id: str) -> dict:
        actor.require("contracts.view")
        run = get_database().one(
            "SELECT r.*,p.name policy_name FROM contract_approval_runs r JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE r.contract_id=? AND r.organisation_id=? ORDER BY r.created_at DESC LIMIT 1",
            (contract_id, actor.organisation_id),
        )
        if not run:
            return {"run": None, "stages": [], "members": []}
        stages = get_database().rows(
            "SELECT * FROM approval_policy_stages WHERE policy_id=? AND organisation_id=? ORDER BY position",
            (run["policy_id"], actor.organisation_id),
        )
        for stage in stages:
            stage["allowed_roles"] = json.loads(stage["allowed_roles_json"])
            stage["decisions"] = get_database().rows(
                "SELECT d.*,a.name actor_name,r.name represented_name FROM approval_stage_decisions d "
                "JOIN users a ON a.id=d.actor_user_id JOIN users r ON r.id=d.represented_user_id "
                "WHERE d.run_id=? AND d.stage_id=? AND d.organisation_id=? ORDER BY d.decided_at",
                (run["id"], stage["id"], actor.organisation_id),
            )
            stage["assignments"] = get_database().rows(
                "SELECT a.*,u.name user_name FROM approval_stage_assignments a JOIN users u ON u.id=a.user_id "
                "WHERE a.run_id=? AND a.stage_id=? AND a.organisation_id=? ORDER BY u.name",
                (run["id"], stage["id"], actor.organisation_id),
            )
        members = get_database().rows(
            "SELECT m.user_id,m.role,u.name FROM memberships m JOIN users u ON u.id=m.user_id "
            "WHERE m.organisation_id=? AND m.role IN ('owner','admin','approver') ORDER BY u.name",
            (actor.organisation_id,),
        )
        return {"run": run, "stages": stages, "members": members}
