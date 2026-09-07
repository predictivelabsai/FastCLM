"""Collaborative drafting, negotiation, and reusable assembly services."""
from __future__ import annotations

import difflib

from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.contracts import ContractService, iso_date
from fastclm.services.identity import new_id, now


class DraftingService:
    def _editable(self, actor: Actor, contract_id: str) -> dict:
        actor.require("contracts.edit")
        contract = get_database().one("SELECT * FROM contracts WHERE id=? AND organisation_id=?", (contract_id, actor.organisation_id))
        if not contract:
            raise LookupError("Contract not found")
        if contract["status"] not in {"draft", "review"}:
            raise ValueError("Collaborative drafting is available only in draft or review")
        return contract

    def workspace(self, actor: Actor, contract_id: str) -> dict:
        actor.require("contracts.view")
        if not get_database().one("SELECT id FROM contracts WHERE id=? AND organisation_id=?", (contract_id, actor.organisation_id)):
            raise LookupError("Contract not found")
        db = get_database()
        redlines = db.rows(
            "SELECT r.*,u.name author_name FROM contract_redlines r LEFT JOIN users u ON u.id=r.created_by WHERE r.contract_id=? AND r.organisation_id=? ORDER BY r.created_at DESC",
            (contract_id, actor.organisation_id),
        )
        for item in redlines:
            item["diff"] = "\n".join(difflib.unified_diff(item["original_text"].splitlines(), item["proposed_text"].splitlines(), fromfile="Current", tofile="Proposed", lineterm=""))
        return {
            "redlines": redlines,
            "comments": db.rows("SELECT c.*,u.name author_name,b.content block_content FROM contract_comments c LEFT JOIN users u ON u.id=c.created_by LEFT JOIN contract_blocks b ON b.id=c.block_id WHERE c.contract_id=? AND c.organisation_id=? ORDER BY c.created_at DESC", (contract_id, actor.organisation_id)),
            "assignments": db.rows("SELECT a.*,u.name assignee_name FROM contract_assignments a JOIN users u ON u.id=a.assigned_to WHERE a.contract_id=? AND a.organisation_id=? ORDER BY a.status,a.due_date", (contract_id, actor.organisation_id)),
            "members": db.rows("SELECT u.id,u.name,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organisation_id=? ORDER BY u.name", (actor.organisation_id,)),
            "clauses": ContractService().clauses(actor),
            "templates": self.templates(actor),
            "playbooks": self.playbooks(actor),
        }

    def insert_clause(self, actor: Actor, contract_id: str, clause_id: str, use_fallback: bool = False) -> dict:
        self._editable(actor, contract_id)
        clause = get_database().one("SELECT * FROM clauses WHERE id=? AND organisation_id=?", (clause_id, actor.organisation_id))
        if not clause:
            raise LookupError("Clause not found")
        content = clause["fallback_body"] if use_fallback and clause["fallback_body"] else clause["body"]
        block = ContractService().add_block(actor, contract_id, "clause", content)
        ContractService().snapshot(actor, contract_id, f"Inserted {clause['title']}")
        return block

    def propose_redline(self, actor: Actor, contract_id: str, operation: str, proposed_text: str, rationale: str = "", block_id: str = "") -> dict:
        self._editable(actor, contract_id)
        if operation not in {"insert", "replace", "delete"}:
            raise ValueError("Unsupported redline operation")
        block = None
        if block_id:
            block = get_database().one("SELECT * FROM contract_blocks WHERE id=? AND contract_id=? AND organisation_id=?", (block_id, contract_id, actor.organisation_id))
            if not block:
                raise LookupError("Contract block not found")
        if operation in {"replace", "delete"} and not block:
            raise ValueError("Replace and delete redlines require a contract block")
        if operation != "delete" and not proposed_text.strip():
            raise ValueError("Proposed wording is required")
        redline_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO contract_redlines(id,organisation_id,contract_id,block_id,operation,original_text,proposed_text,rationale,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (redline_id, actor.organisation_id, contract_id, block_id or None, operation, block["content"] if block else "", proposed_text.strip(), rationale.strip(), actor.user_id, created))
            AuditService().record(actor, "contract_redline", redline_id, "redline.proposed", {"contract_id": contract_id, "operation": operation}, tx)
        return get_database().one("SELECT * FROM contract_redlines WHERE id=?", (redline_id,))

    def decide_redline(self, actor: Actor, redline_id: str, accept: bool) -> dict:
        actor.require("contracts.edit")
        row = get_database().one("SELECT * FROM contract_redlines WHERE id=? AND organisation_id=?", (redline_id, actor.organisation_id))
        if not row:
            raise LookupError("Redline not found")
        if row["status"] != "pending":
            raise ValueError("Redline has already been decided")
        self._editable(actor, row["contract_id"])
        if accept:
            if row["operation"] == "insert":
                ContractService().add_block(actor, row["contract_id"], "clause", row["proposed_text"])
            elif row["operation"] == "replace":
                ContractService().update_block(actor, row["contract_id"], row["block_id"], "clause", row["proposed_text"])
            else:
                with get_database().transaction() as tx:
                    tx.execute("DELETE FROM contract_blocks WHERE id=? AND contract_id=? AND organisation_id=?", (row["block_id"], row["contract_id"], actor.organisation_id))
                    AuditService().record(actor, "contract", row["contract_id"], "block.deleted", {"block_id": row["block_id"]}, tx)
            ContractService().snapshot(actor, row["contract_id"], "Accepted redline")
        decided = now()
        with get_database().transaction() as tx:
            tx.execute("UPDATE contract_redlines SET status=?,decided_by=?,decided_at=? WHERE id=? AND organisation_id=?", ("accepted" if accept else "rejected", actor.user_id, decided, redline_id, actor.organisation_id))
            AuditService().record(actor, "contract_redline", redline_id, "redline.accepted" if accept else "redline.rejected", {"contract_id": row["contract_id"]}, tx)
        return get_database().one("SELECT * FROM contract_redlines WHERE id=?", (redline_id,))

    def add_comment(self, actor: Actor, contract_id: str, body: str, block_id: str = "", mention_user_ids: list[str] | None = None) -> dict:
        actor.require("contracts.view")
        ContractService()._contract(actor, contract_id)
        if not body.strip():
            raise ValueError("Comment is required")
        if block_id and not get_database().one("SELECT id FROM contract_blocks WHERE id=? AND contract_id=? AND organisation_id=?", (block_id, contract_id, actor.organisation_id)):
            raise ValueError("Comment block is not in this contract")
        mentions = list(dict.fromkeys(mention_user_ids or []))
        for user_id in mentions:
            if not get_database().one("SELECT 1 FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, user_id)):
                raise ValueError("Mentioned user is not in this workspace")
        comment_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO contract_comments(id,organisation_id,contract_id,block_id,body,created_by,created_at) VALUES (?,?,?,?,?,?,?)", (comment_id, actor.organisation_id, contract_id, block_id or None, body.strip(), actor.user_id, created))
            for user_id in mentions:
                tx.execute("INSERT INTO comment_mentions(organisation_id,comment_id,user_id,created_at) VALUES (?,?,?,?)", (actor.organisation_id, comment_id, user_id, created))
            AuditService().record(actor, "contract_comment", comment_id, "comment.created", {"contract_id": contract_id, "mentions": mentions}, tx)
        return get_database().one("SELECT * FROM contract_comments WHERE id=?", (comment_id,))

    def resolve_comment(self, actor: Actor, comment_id: str) -> dict:
        actor.require("contracts.edit")
        row = get_database().one("SELECT * FROM contract_comments WHERE id=? AND organisation_id=?", (comment_id, actor.organisation_id))
        if not row:
            raise LookupError("Comment not found")
        with get_database().transaction() as tx:
            tx.execute("UPDATE contract_comments SET status='resolved',resolved_by=?,resolved_at=? WHERE id=? AND organisation_id=?", (actor.user_id, now(), comment_id, actor.organisation_id))
            AuditService().record(actor, "contract_comment", comment_id, "comment.resolved", {"contract_id": row["contract_id"]}, tx)
        return get_database().one("SELECT * FROM contract_comments WHERE id=?", (comment_id,))

    def assign(self, actor: Actor, contract_id: str, title: str, assigned_to: str, due_date: str = "", description: str = "", comment_id: str = "") -> dict:
        actor.require("contracts.edit")
        ContractService()._contract(actor, contract_id)
        if not title.strip() or not get_database().one("SELECT 1 FROM memberships WHERE organisation_id=? AND user_id=?", (actor.organisation_id, assigned_to)):
            raise ValueError("A title and workspace assignee are required")
        if comment_id and not get_database().one("SELECT id FROM contract_comments WHERE id=? AND contract_id=? AND organisation_id=?", (comment_id, contract_id, actor.organisation_id)):
            raise ValueError("Assignment comment is not in this contract")
        assignment_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO contract_assignments(id,organisation_id,contract_id,comment_id,title,description,assigned_to,due_date,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (assignment_id, actor.organisation_id, contract_id, comment_id or None, title.strip(), description.strip(), assigned_to, iso_date(due_date, "Due date"), actor.user_id, created))
            AuditService().record(actor, "contract_assignment", assignment_id, "assignment.created", {"contract_id": contract_id, "assigned_to": assigned_to}, tx)
        return get_database().one("SELECT * FROM contract_assignments WHERE id=?", (assignment_id,))

    def complete_assignment(self, actor: Actor, assignment_id: str) -> dict:
        row = get_database().one("SELECT * FROM contract_assignments WHERE id=? AND organisation_id=?", (assignment_id, actor.organisation_id))
        if not row:
            raise LookupError("Assignment not found")
        if row["assigned_to"] != actor.user_id and not actor.can("contracts.edit"):
            raise PermissionError("Only the assignee or an editor can complete this assignment")
        with get_database().transaction() as tx:
            tx.execute("UPDATE contract_assignments SET status='complete',completed_at=? WHERE id=? AND organisation_id=?", (now(), assignment_id, actor.organisation_id))
            AuditService().record(actor, "contract_assignment", assignment_id, "assignment.completed", {"contract_id": row["contract_id"]}, tx)
        return get_database().one("SELECT * FROM contract_assignments WHERE id=?", (assignment_id,))

    def templates(self, actor: Actor) -> list[dict]:
        actor.require("contracts.view")
        return get_database().rows("SELECT * FROM contract_templates WHERE organisation_id=? ORDER BY name", (actor.organisation_id,))

    def create_template(self, actor: Actor, data: dict) -> dict:
        actor.require("clauses.manage")
        name, blocks = str(data.get("name", "")).strip(), data.get("blocks") or []
        if not name or not blocks:
            raise ValueError("Template name and blocks are required")
        template_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO contract_templates(id,organisation_id,name,description,contract_type,jurisdiction,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (template_id, actor.organisation_id, name, str(data.get("description", "")).strip(), str(data.get("contract_type", "Commercial agreement")), str(data.get("jurisdiction", "UK / EU")), actor.user_id, created, created))
            for position, block in enumerate(blocks):
                block_type = block.get("block_type", "paragraph")
                if block_type not in {"heading", "paragraph", "list", "quote", "clause"}:
                    raise ValueError("Unsupported template block type")
                tx.execute("INSERT INTO contract_template_blocks(id,organisation_id,template_id,position,block_type,content) VALUES (?,?,?,?,?,?)", (new_id(), actor.organisation_id, template_id, position, block_type, str(block.get("content", "")).strip()))
            AuditService().record(actor, "contract_template", template_id, "template.created", {"name": name, "blocks": len(blocks)}, tx)
        return get_database().one("SELECT * FROM contract_templates WHERE id=?", (template_id,))

    def assemble_template(self, actor: Actor, template_id: str, data: dict) -> dict:
        actor.require("contracts.edit")
        template = get_database().one("SELECT * FROM contract_templates WHERE id=? AND organisation_id=?", (template_id, actor.organisation_id))
        if not template:
            raise LookupError("Template not found")
        blocks = get_database().rows("SELECT block_type,content FROM contract_template_blocks WHERE template_id=? AND organisation_id=? ORDER BY position", (template_id, actor.organisation_id))
        payload = dict(data) | {"contract_type": template["contract_type"], "jurisdiction": template["jurisdiction"]}
        contract = ContractService().create(actor, payload)
        ContractService().replace_blocks(actor, contract["id"], blocks)
        ContractService().snapshot(actor, contract["id"], f"Assembled from {template['name']}")
        return ContractService().get(actor, contract["id"])

    def playbooks(self, actor: Actor) -> list[dict]:
        actor.require("contracts.view")
        return get_database().rows("SELECT * FROM negotiation_playbooks WHERE organisation_id=? ORDER BY name", (actor.organisation_id,))

    def create_playbook(self, actor: Actor, data: dict) -> dict:
        actor.require("clauses.manage")
        name, clause_ids = str(data.get("name", "")).strip(), list(dict.fromkeys(data.get("clause_ids") or []))
        if not name or not clause_ids:
            raise ValueError("Playbook name and clauses are required")
        playbook_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO negotiation_playbooks(id,organisation_id,name,contract_type,jurisdiction,created_by,created_at) VALUES (?,?,?,?,?,?,?)", (playbook_id, actor.organisation_id, name, str(data.get("contract_type", "Commercial agreement")), str(data.get("jurisdiction", "UK / EU")), actor.user_id, created))
            for position, clause_id in enumerate(clause_ids):
                if not tx.one("SELECT id FROM clauses WHERE id=? AND organisation_id=?", (clause_id, actor.organisation_id)):
                    raise ValueError("Playbook clause is not in this workspace")
                tx.execute("INSERT INTO negotiation_playbook_clauses(id,organisation_id,playbook_id,clause_id,position,negotiation_note) VALUES (?,?,?,?,?,?)", (new_id(), actor.organisation_id, playbook_id, clause_id, position, str(data.get("negotiation_note", "")).strip()))
            AuditService().record(actor, "negotiation_playbook", playbook_id, "playbook.created", {"name": name, "clauses": len(clause_ids)}, tx)
        return get_database().one("SELECT * FROM negotiation_playbooks WHERE id=?", (playbook_id,))

    def apply_playbook(self, actor: Actor, contract_id: str, playbook_id: str, use_fallback: bool = False) -> list[dict]:
        self._editable(actor, contract_id)
        if not get_database().one("SELECT id FROM negotiation_playbooks WHERE id=? AND organisation_id=?", (playbook_id, actor.organisation_id)):
            raise LookupError("Playbook not found")
        clauses = get_database().rows(
            "SELECT c.* FROM negotiation_playbook_clauses pc JOIN clauses c ON c.id=pc.clause_id AND c.organisation_id=pc.organisation_id WHERE pc.playbook_id=? AND pc.organisation_id=? ORDER BY pc.position",
            (playbook_id, actor.organisation_id),
        )
        inserted = []
        for clause in clauses:
            content = clause["fallback_body"] if use_fallback and clause["fallback_body"] else clause["body"]
            inserted.append(ContractService().add_block(actor, contract_id, "clause", content))
        ContractService().snapshot(actor, contract_id, "Applied negotiation playbook fallback" if use_fallback else "Applied negotiation playbook")
        return inserted
