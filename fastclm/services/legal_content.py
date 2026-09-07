"""Evidence-backed governance for external legal review of clause wording."""
from __future__ import annotations

import hashlib
import json
import re

from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.identity import new_id, now


DECISIONS = {"approved", "changes_requested", "not_approved"}


def wording_checksum(clause: dict) -> str:
    material = "\n".join((clause["body"], clause["fallback_body"], clause["risk_guidance"]))
    return hashlib.sha256(material.encode()).hexdigest()


class LegalContentService:
    def overview(self, actor: Actor) -> dict:
        actor.require("contracts.view")
        database = get_database()
        clauses = database.rows("SELECT * FROM clauses WHERE organisation_id=? ORDER BY category,title", (actor.organisation_id,))
        reviews = database.rows(
            "SELECT r.*,c.title clause_title FROM clause_legal_reviews r JOIN clauses c ON c.id=r.clause_id "
            "WHERE r.organisation_id=? ORDER BY r.created_at DESC",
            (actor.organisation_id,),
        )
        latest: dict[str, dict] = {}
        for review in reviews:
            latest.setdefault(review["clause_id"], review)
        counts = {"approved": 0, "attention": 0, "unreviewed": 0}
        for clause in clauses:
            review = latest.get(clause["id"])
            if not review:
                status = "unreviewed"
                counts["unreviewed"] += 1
            elif review["wording_checksum"] != wording_checksum(clause):
                status = "stale"
                counts["attention"] += 1
            else:
                status = review["decision"]
                counts["approved" if status == "approved" else "attention"] += 1
            clause["legal_review_status"] = status
            clause["legal_review"] = review
        return {
            "clauses": clauses,
            "reviews": reviews,
            "requests": database.rows(
                "SELECT q.*,u.name requested_by_name FROM legal_review_requests q LEFT JOIN users u ON u.id=q.requested_by "
                "WHERE q.organisation_id=? ORDER BY q.created_at DESC",
                (actor.organisation_id,),
            ),
            "counts": counts,
        }

    def request_review(self, actor: Actor, data: dict) -> dict:
        actor.require("clauses.manage")
        scope = str(data.get("scope", "")).strip()
        jurisdiction = str(data.get("jurisdiction", "")).strip()
        reviewer_name = str(data.get("reviewer_name", "")).strip()
        reviewer_email = str(data.get("reviewer_email", "")).strip().lower()
        clause_ids = list(dict.fromkeys(str(item) for item in data.get("clause_ids", []) if str(item)))
        if not scope or not jurisdiction or not clause_ids:
            raise ValueError("Review scope, jurisdiction, and at least one clause are required")
        if reviewer_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reviewer_email):
            raise ValueError("Reviewer email is invalid")
        placeholders = ",".join("?" for _ in clause_ids)
        found = get_database().rows(
            f"SELECT id FROM clauses WHERE organisation_id=? AND id IN ({placeholders})",
            (actor.organisation_id, *clause_ids),
        )
        if len(found) != len(clause_ids):
            raise LookupError("One or more clauses are not in this workspace")
        request_id, created = new_id(), now()
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO legal_review_requests(id,organisation_id,scope,jurisdiction,clause_ids_json,reviewer_name,reviewer_email,status,requested_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,'open',?,?)",
                (request_id, actor.organisation_id, scope, jurisdiction, json.dumps(clause_ids), reviewer_name, reviewer_email, actor.user_id, created),
            )
            AuditService().record(actor, "legal_review_request", request_id, "legal_content.review_requested", {
                "jurisdiction": jurisdiction, "clause_ids": clause_ids, "reviewer_assigned": bool(reviewer_name or reviewer_email),
            }, tx)
        return get_database().one("SELECT * FROM legal_review_requests WHERE id=? AND organisation_id=?", (request_id, actor.organisation_id))

    def record_review(self, actor: Actor, data: dict) -> dict:
        actor.require("clauses.manage")
        clause_id = str(data.get("clause_id", "")).strip()
        request_id = str(data.get("request_id", "")).strip()
        decision = str(data.get("decision", "")).strip()
        reviewed_jurisdiction = str(data.get("reviewed_jurisdiction", "")).strip()
        reviewer_name = str(data.get("reviewer_name", "")).strip()
        reviewer_organisation = str(data.get("reviewer_organisation", "")).strip()
        reviewer_qualification = str(data.get("reviewer_qualification", "")).strip()
        evidence_reference = str(data.get("evidence_reference", "")).strip()
        notes = str(data.get("notes", "")).strip()
        attested = str(data.get("qualification_attested", "")).lower() in {"1", "true", "on", "yes"}
        if decision not in DECISIONS:
            raise ValueError("Choose a valid review decision")
        if not all((reviewed_jurisdiction, reviewer_name, reviewer_organisation, reviewer_qualification, evidence_reference)):
            raise ValueError("Jurisdiction, reviewer identity, qualification, organisation, and evidence are required")
        if not attested:
            raise ValueError("Confirm that the named reviewer is qualified for the stated jurisdiction")
        database = get_database()
        clause = database.one("SELECT * FROM clauses WHERE id=? AND organisation_id=?", (clause_id, actor.organisation_id))
        if not clause:
            raise LookupError("Clause not found")
        if request_id:
            request = database.one(
                "SELECT * FROM legal_review_requests WHERE id=? AND organisation_id=? AND status='open'",
                (request_id, actor.organisation_id),
            )
            if not request or clause_id not in json.loads(request["clause_ids_json"]):
                raise LookupError("Open review request does not cover this clause")
        review_id, created = new_id(), now()
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO clause_legal_reviews(id,organisation_id,clause_id,request_id,wording_checksum,decision,reviewed_jurisdiction,"
                "reviewer_name,reviewer_organisation,reviewer_qualification,evidence_reference,notes,qualification_attested,recorded_by,reviewed_at,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (review_id, actor.organisation_id, clause_id, request_id or None, wording_checksum(clause), decision, reviewed_jurisdiction,
                 reviewer_name, reviewer_organisation, reviewer_qualification, evidence_reference, notes, actor.user_id, created, created),
            )
            if request_id:
                reviewed_clause_ids = {
                    row["clause_id"] for row in tx.rows(
                        "SELECT DISTINCT clause_id FROM clause_legal_reviews WHERE request_id=? AND organisation_id=?",
                        (request_id, actor.organisation_id),
                    )
                }
                if set(json.loads(request["clause_ids_json"])) <= reviewed_clause_ids:
                    tx.execute(
                        "UPDATE legal_review_requests SET status='completed',closed_by=?,closed_at=? WHERE id=? AND organisation_id=?",
                        (actor.user_id, created, request_id, actor.organisation_id),
                    )
            AuditService().record(actor, "clause_legal_review", review_id, "legal_content.review_recorded", {
                "clause_id": clause_id, "decision": decision, "jurisdiction": reviewed_jurisdiction,
                "wording_checksum": wording_checksum(clause), "request_id": request_id,
            }, tx)
        return database.one("SELECT * FROM clause_legal_reviews WHERE id=? AND organisation_id=?", (review_id, actor.organisation_id))
