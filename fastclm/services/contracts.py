"""Contract lifecycle, version, obligation, and clause operations."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastclm.database import get_database
from fastclm.lifecycle import next_statuses, require_transition
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now


def money(value: str) -> str:
    value = value.strip().replace(",", "")
    if not value:
        return ""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Contract value must be a decimal number") from exc
    if amount < 0:
        raise ValueError("Contract value cannot be negative")
    return format(amount.quantize(Decimal("0.01")), "f")


def blocks_to_text(blocks: list[dict]) -> str:
    return "\n\n".join(str(block["content"]).strip() for block in blocks if str(block["content"]).strip())


def text_to_blocks(text: str) -> list[dict]:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    result = []
    for paragraph in paragraphs:
        first = paragraph.splitlines()[0]
        block_type = "heading" if len(first) < 90 and (first.isupper() or first.rstrip().endswith(":") or first[:3].rstrip(".").isdigit()) else "paragraph"
        result.append({"block_type": block_type, "content": paragraph})
    return result or [{"block_type": "paragraph", "content": ""}]


class ContractService:
    def _contract(self, actor: Actor, contract_id: str) -> dict:
        row = get_database().one(
            "SELECT c.*,p.name counterparty_name,u.name owner_name FROM contracts c "
            "LEFT JOIN counterparties p ON p.id=c.counterparty_id LEFT JOIN users u ON u.id=c.owner_user_id "
            "WHERE c.id=? AND c.organisation_id=?",
            (contract_id, actor.organisation_id),
        )
        if not row:
            raise LookupError("Contract not found")
        return row

    def get(self, actor: Actor, contract_id: str) -> dict:
        actor.require("contracts.view")
        item = self._contract(actor, contract_id)
        item["blocks"] = self.blocks(actor, contract_id)
        item["versions"] = get_database().rows("SELECT * FROM contract_versions WHERE contract_id=? AND organisation_id=? ORDER BY version_number DESC", (contract_id, actor.organisation_id))
        item["obligations"] = get_database().rows("SELECT * FROM obligations WHERE contract_id=? AND organisation_id=? ORDER BY status,due_date", (contract_id, actor.organisation_id))
        item["approvals"] = get_database().rows("SELECT a.*,u.name approver_name FROM approvals a JOIN users u ON u.id=a.approver_user_id WHERE a.contract_id=? AND a.organisation_id=? ORDER BY decided_at DESC", (contract_id, actor.organisation_id))
        item["signatures"] = get_database().rows("SELECT * FROM signature_requests WHERE contract_id=? AND organisation_id=? ORDER BY created_at DESC", (contract_id, actor.organisation_id))
        item["findings"] = get_database().rows("SELECT * FROM review_findings WHERE contract_id=? AND organisation_id=? ORDER BY created_at DESC LIMIT 5", (contract_id, actor.organisation_id))
        item["next_statuses"] = next_statuses(item["status"])
        return item

    def list(self, actor: Actor, q: str = "", status: str = "") -> list[dict]:
        actor.require("contracts.view")
        where = ["c.organisation_id=?"]
        params: list[str] = [actor.organisation_id]
        if status:
            where.append("c.status=?")
            params.append(status)
        if q.strip():
            where.append("(lower(c.title) LIKE ? OR lower(c.reference) LIKE ? OR lower(COALESCE(p.name,'')) LIKE ?)")
            needle = f"%{q.strip().lower()}%"
            params.extend([needle, needle, needle])
        return get_database().rows(
            "SELECT c.*,p.name counterparty_name,u.name owner_name FROM contracts c "
            "LEFT JOIN counterparties p ON p.id=c.counterparty_id LEFT JOIN users u ON u.id=c.owner_user_id "
            f"WHERE {' AND '.join(where)} ORDER BY c.updated_at DESC",
            params,
        )

    def dashboard(self, actor: Actor) -> dict:
        actor.require("contracts.view")
        db = get_database()
        org = actor.organisation_id
        today = date.today().isoformat()
        soon = (date.today() + timedelta(days=90)).isoformat()
        return {
            "total": db.scalar("SELECT COUNT(*) FROM contracts WHERE organisation_id=?", (org,)) or 0,
            "active": db.scalar("SELECT COUNT(*) FROM contracts WHERE organisation_id=? AND status='active'", (org,)) or 0,
            "in_review": db.scalar("SELECT COUNT(*) FROM contracts WHERE organisation_id=? AND status IN ('review','approval','signature')", (org,)) or 0,
            "expiring": db.scalar("SELECT COUNT(*) FROM contracts WHERE organisation_id=? AND status='active' AND expiry_date BETWEEN ? AND ?", (org, today, soon)) or 0,
            "overdue": db.scalar("SELECT COUNT(*) FROM obligations WHERE organisation_id=? AND status='open' AND due_date<>'' AND due_date<?", (org, today)) or 0,
            "recent": self.list(actor)[:6],
            "upcoming": db.rows("SELECT o.*,c.title contract_title,c.reference FROM obligations o JOIN contracts c ON c.id=o.contract_id WHERE o.organisation_id=? AND o.status='open' ORDER BY CASE WHEN o.due_date='' THEN 1 ELSE 0 END,o.due_date LIMIT 6", (org,)),
        }

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("contracts.edit")
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValueError("Contract title is required")
        db, contract_id, created = get_database(), new_id(), now()
        counterparty_id = str(data.get("counterparty_id", "")).strip() or None
        if counterparty_id and not db.one("SELECT id FROM counterparties WHERE id=? AND organisation_id=?", (counterparty_id, actor.organisation_id)):
            raise ValueError("Counterparty is not in this workspace")
        reference = str(data.get("reference", "")).strip()
        if not reference:
            sequence = int(db.scalar("SELECT COUNT(*) FROM contracts WHERE organisation_id=?", (actor.organisation_id,)) or 0) + 1
            reference = f"CLM-{date.today().year}-{sequence:04d}"
        params = (
            contract_id, actor.organisation_id, counterparty_id, actor.user_id, reference, title,
            str(data.get("contract_type", "Commercial agreement")).strip() or "Commercial agreement",
            str(data.get("jurisdiction", "England and Wales")).strip() or "England and Wales",
            str(data.get("summary", "")).strip(), money(str(data.get("value_amount", ""))),
            str(data.get("currency", "GBP")).strip().upper()[:3] or "GBP",
            str(data.get("effective_date", "")), str(data.get("expiry_date", "")), str(data.get("notice_date", "")),
            str(data.get("renewal_type", "none")), created, created,
        )
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO contracts(id,organisation_id,counterparty_id,owner_user_id,reference,title,contract_type,jurisdiction,summary,value_amount,currency,effective_date,expiry_date,notice_date,renewal_type,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                params,
            )
            tx.execute("INSERT INTO contract_blocks(id,organisation_id,contract_id,position,block_type,content,updated_at) VALUES (?,?,?,?,?,?,?)", (new_id(), actor.organisation_id, contract_id, 0, "heading", title, created))
            AuditService().record(actor, "contract", contract_id, "contract.created", {"reference": reference}, tx)
        self.snapshot(actor, contract_id, "Initial draft")
        return self._contract(actor, contract_id)

    def transition(self, actor: Actor, contract_id: str, target: str) -> dict:
        actor.require("contracts.transition")
        item = self._contract(actor, contract_id)
        require_transition(item["status"], target)
        if item["status"] == "approval" and target == "signature":
            raise ValueError("Record an approval decision to move the contract to signature")
        if target == "active" and not get_database().scalar("SELECT COUNT(*) FROM approvals WHERE contract_id=? AND decision='approved'", (contract_id,)):
            raise ValueError("At least one recorded approval is required before activation")
        with get_database().transaction() as tx:
            tx.execute("UPDATE contracts SET status=?,updated_at=? WHERE id=? AND organisation_id=?", (target, now(), contract_id, actor.organisation_id))
            AuditService().record(actor, "contract", contract_id, "contract.transitioned", {"from": item["status"], "to": target}, tx)
        return self._contract(actor, contract_id)

    def blocks(self, actor: Actor, contract_id: str) -> list[dict]:
        self._contract(actor, contract_id)
        return get_database().rows("SELECT * FROM contract_blocks WHERE contract_id=? AND organisation_id=? ORDER BY position,id", (contract_id, actor.organisation_id))

    def add_block(self, actor: Actor, contract_id: str, block_type: str, content: str) -> dict:
        actor.require("contracts.edit")
        item = self._contract(actor, contract_id)
        if item["status"] not in {"draft", "review"}:
            raise ValueError("Only draft or review contracts can be edited")
        if block_type not in {"heading", "paragraph", "list", "quote", "clause"}:
            raise ValueError("Unsupported block type")
        position = int(get_database().scalar("SELECT COALESCE(MAX(position),-1)+1 FROM contract_blocks WHERE contract_id=?", (contract_id,)) or 0)
        block_id, updated = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO contract_blocks(id,organisation_id,contract_id,position,block_type,content,updated_at) VALUES (?,?,?,?,?,?,?)", (block_id, actor.organisation_id, contract_id, position, block_type, content.strip(), updated))
            tx.execute("UPDATE contracts SET updated_at=? WHERE id=?", (updated, contract_id))
            AuditService().record(actor, "contract", contract_id, "block.added", {"block_id": block_id, "type": block_type}, tx)
        return get_database().one("SELECT * FROM contract_blocks WHERE id=?", (block_id,))

    def update_block(self, actor: Actor, contract_id: str, block_id: str, block_type: str, content: str) -> None:
        actor.require("contracts.edit")
        item = self._contract(actor, contract_id)
        if item["status"] not in {"draft", "review"}:
            raise ValueError("Only draft or review contracts can be edited")
        if block_type not in {"heading", "paragraph", "list", "quote", "clause"}:
            raise ValueError("Unsupported block type")
        with get_database().transaction() as tx:
            result = tx.execute("UPDATE contract_blocks SET block_type=?,content=?,updated_at=? WHERE id=? AND contract_id=? AND organisation_id=?", (block_type, content.strip(), now(), block_id, contract_id, actor.organisation_id))
            if result.rowcount != 1:
                raise LookupError("Block not found")
            tx.execute("UPDATE contracts SET updated_at=? WHERE id=?", (now(), contract_id))
            AuditService().record(actor, "contract", contract_id, "block.updated", {"block_id": block_id}, tx)

    def replace_blocks(self, actor: Actor, contract_id: str, blocks: list[dict]) -> None:
        actor.require("contracts.edit")
        item = self._contract(actor, contract_id)
        if item["status"] not in {"draft", "review"}:
            raise ValueError("Only draft or review contracts can be edited")
        updated = now()
        with get_database().transaction() as tx:
            tx.execute("DELETE FROM contract_blocks WHERE contract_id=? AND organisation_id=?", (contract_id, actor.organisation_id))
            for position, block in enumerate(blocks):
                tx.execute("INSERT INTO contract_blocks(id,organisation_id,contract_id,position,block_type,content,updated_at) VALUES (?,?,?,?,?,?,?)", (new_id(), actor.organisation_id, contract_id, position, block["block_type"], block["content"], updated))
            tx.execute("UPDATE contracts SET updated_at=? WHERE id=?", (updated, contract_id))
            AuditService().record(actor, "contract", contract_id, "document.imported", {"blocks": len(blocks)}, tx)

    def snapshot(self, actor: Actor, contract_id: str, label: str = "Saved version", *, source_filename: str = "", storage_path: str = "", media_type: str = "", byte_size: int = 0) -> dict:
        actor.require("contracts.edit")
        blocks = self.blocks(actor, contract_id)
        body = blocks_to_text(blocks)
        content_json = json.dumps([{"type": block["block_type"], "content": block["content"]} for block in blocks], ensure_ascii=False)
        checksum = hashlib.sha256((content_json + source_filename).encode()).hexdigest()
        db = get_database()
        number = int(db.scalar("SELECT COALESCE(MAX(version_number),0)+1 FROM contract_versions WHERE contract_id=?", (contract_id,)) or 1)
        version_id, created = new_id(), now()
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO contract_versions(id,organisation_id,contract_id,version_number,label,body_text,content_json,source_filename,storage_path,media_type,byte_size,checksum,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (version_id, actor.organisation_id, contract_id, number, label.strip(), body, content_json, source_filename, storage_path, media_type, byte_size, checksum, actor.user_id, created),
            )
            AuditService().record(actor, "contract", contract_id, "version.created", {"version": number, "filename": source_filename, "checksum": checksum}, tx)
        return db.one("SELECT * FROM contract_versions WHERE id=?", (version_id,))

    def add_obligation(self, actor: Actor, contract_id: str, data: dict) -> dict:
        actor.require("obligations.manage")
        self._contract(actor, contract_id)
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValueError("Obligation title is required")
        obligation_id, created = new_id(), now()
        recurrence = str(data.get("recurrence", "none"))
        if recurrence not in {"none", "monthly", "quarterly", "annual"}:
            raise ValueError("Unsupported recurrence")
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO obligations(id,organisation_id,contract_id,title,description,owner_user_id,due_date,recurrence,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (obligation_id, actor.organisation_id, contract_id, title, str(data.get("description", "")).strip(), actor.user_id, str(data.get("due_date", "")), recurrence, created))
            AuditService().record(actor, "obligation", obligation_id, "obligation.created", {"contract_id": contract_id, "due_date": str(data.get("due_date", ""))}, tx)
        return get_database().one("SELECT * FROM obligations WHERE id=?", (obligation_id,))

    def complete_obligation(self, actor: Actor, obligation_id: str) -> None:
        actor.require("obligations.manage")
        row = get_database().one("SELECT * FROM obligations WHERE id=? AND organisation_id=?", (obligation_id, actor.organisation_id))
        if not row:
            raise LookupError("Obligation not found")
        if row["status"] != "open":
            return
        with get_database().transaction() as tx:
            tx.execute("UPDATE obligations SET status='complete',completed_at=? WHERE id=? AND organisation_id=?", (now(), obligation_id, actor.organisation_id))
            AuditService().record(actor, "obligation", obligation_id, "obligation.completed", {"contract_id": row["contract_id"]}, tx)

    def approve(self, actor: Actor, contract_id: str, decision: str, comment: str = "") -> dict:
        actor.require("contracts.approve")
        item = self._contract(actor, contract_id)
        if item["status"] != "approval":
            raise ValueError("Contract is not awaiting approval")
        if decision not in {"approved", "changes_requested"}:
            raise ValueError("Unsupported approval decision")
        approval_id, decided = new_id(), now()
        target = "signature" if decision == "approved" else "review"
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO approvals(id,organisation_id,contract_id,approver_user_id,decision,comment,decided_at) VALUES (?,?,?,?,?,?,?)", (approval_id, actor.organisation_id, contract_id, actor.user_id, decision, comment.strip(), decided))
            tx.execute("UPDATE contracts SET status=?,updated_at=? WHERE id=?", (target, decided, contract_id))
            AuditService().record(actor, "contract", contract_id, "approval.recorded", {"decision": decision, "to": target}, tx)
        return get_database().one("SELECT * FROM approvals WHERE id=?", (approval_id,))

    def obligations(self, actor: Actor, status: str = "open") -> list[dict]:
        actor.require("contracts.view")
        where = "o.organisation_id=?"
        params = [actor.organisation_id]
        if status:
            where += " AND o.status=?"
            params.append(status)
        return get_database().rows("SELECT o.*,c.title contract_title,c.reference,u.name owner_name FROM obligations o JOIN contracts c ON c.id=o.contract_id LEFT JOIN users u ON u.id=o.owner_user_id WHERE " + where + " ORDER BY CASE WHEN o.due_date='' THEN 1 ELSE 0 END,o.due_date", params)

    def counterparties(self, actor: Actor) -> list[dict]:
        actor.require("contracts.view")
        return get_database().rows("SELECT p.*,(SELECT COUNT(*) FROM contracts c WHERE c.counterparty_id=p.id) contract_count FROM counterparties p WHERE p.organisation_id=? ORDER BY p.name", (actor.organisation_id,))

    def add_counterparty(self, actor: Actor, data: dict) -> dict:
        actor.require("contracts.edit")
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Counterparty name is required")
        party_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO counterparties(id,organisation_id,name,registration_number,jurisdiction,contact_name,contact_email,created_at) VALUES (?,?,?,?,?,?,?,?)", (party_id, actor.organisation_id, name, str(data.get("registration_number", "")).strip(), str(data.get("jurisdiction", "")).strip(), str(data.get("contact_name", "")).strip(), str(data.get("contact_email", "")).strip(), created))
            AuditService().record(actor, "counterparty", party_id, "counterparty.created", {"name": name}, tx)
        return get_database().one("SELECT * FROM counterparties WHERE id=?", (party_id,))

    def clauses(self, actor: Actor) -> list[dict]:
        actor.require("contracts.view")
        return get_database().rows("SELECT * FROM clauses WHERE organisation_id=? ORDER BY category,title", (actor.organisation_id,))

    def add_clause(self, actor: Actor, data: dict) -> dict:
        actor.require("clauses.manage")
        title, body = str(data.get("title", "")).strip(), str(data.get("body", "")).strip()
        if not title or not body:
            raise ValueError("Clause title and body are required")
        clause_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO clauses(id,organisation_id,title,category,jurisdiction,body,fallback_body,risk_guidance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (clause_id, actor.organisation_id, title, str(data.get("category", "General")).strip(), str(data.get("jurisdiction", "UK / EU")).strip(), body, str(data.get("fallback_body", "")).strip(), str(data.get("risk_guidance", "")).strip(), created, created))
            AuditService().record(actor, "clause", clause_id, "clause.created", {"title": title}, tx)
        return get_database().one("SELECT * FROM clauses WHERE id=?", (clause_id,))
