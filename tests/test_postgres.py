from __future__ import annotations

import os

import pytest

from fastclm.database import Database, set_database
from fastclm.services.contracts import ContractService
from fastclm.services.assistant import AssistantService
from fastclm.services.identity import IdentityService
from fastclm.services.legal_content import LegalContentService
from fastclm.services.notifications import NotificationService


@pytest.mark.skipif(not os.getenv("FASTCLM_TEST_POSTGRES_URL"), reason="requires an isolated PostgreSQL test database")
def test_postgres_migrations_repository_search_and_tenant_isolation():
    database = Database(database_url=os.environ["FASTCLM_TEST_POSTGRES_URL"])
    try:
        assert database.migrate() == [f"{number:04d}_{name}" for number, name in [
            (1, "baseline"),
            (2, "notifications"),
            (3, "account_recovery"),
            (4, "document_integrity"),
            (5, "ai_cockpit"),
            (6, "streaming_citations"),
            (7, "team_scim"),
            (8, "document_infrastructure"),
            (9, "grounded_matters"),
            (10, "collaborative_drafting"),
            (11, "approval_workflows"),
            (12, "signature_execution"),
            (13, "notification_governance"),
            (14, "full_text_search"),
            (15, "legal_content_governance"),
        ]]
        set_database(database)
        identity = IdentityService()
        user, organisation = identity.create_workspace(
            "postgres-owner@example.test", "A-secure-passphrase1!", "Owner", "PostgreSQL Studio"
        )
        actor = identity.actor(user["id"], organisation["id"])
        assistant = AssistantService()
        thread = assistant.ensure_workspace(actor)
        assert assistant.cockpit(actor, thread["id"])["thread"]["id"] == thread["id"]
        contracts = ContractService()
        counterparty = contracts.add_counterparty(actor, {"name": "Quasar Systems Ltd"})
        agreement = contracts.create(actor, {"title": "Services framework", "counterparty_id": counterparty["id"]})
        contracts.add_block(actor, agreement["id"], "clause", "Sublicensing requires written consent.")
        assert [item["id"] for item in contracts.list(actor, "sublicens")] == [agreement["id"]]
        contracts.snapshot(actor, agreement["id"], "PostgreSQL draft")
        contracts.transition(actor, agreement["id"], "review")
        contracts.transition(actor, agreement["id"], "approval")
        contracts.approve(actor, agreement["id"], "approved", "Repository parity check")
        assert contracts.get(actor, agreement["id"])["status"] == "signature"
        assert len(contracts.get(actor, agreement["id"])["versions"]) == 2
        assert len(NotificationService().overview(actor)["templates"]) == 3
        clause = contracts.clauses(actor)[0]
        review_request = LegalContentService().request_review(actor, {
            "scope": "PostgreSQL evidence workflow", "jurisdiction": "England and Wales", "clause_ids": [clause["id"]],
        })
        assert review_request["status"] == "open"
        other_user, other_org = identity.create_workspace(
            "postgres-other@example.test", "Another-secure-pass1!", "Other", "Other PostgreSQL Studio"
        )
        other_actor = identity.actor(other_user["id"], other_org["id"])
        assert contracts.list(other_actor, "sublicens") == []
        assert database.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=?", (organisation["id"],)) >= 3
        assert "contract_search" in database.table_names()
        assert {"organisation_id", "search_vector"} <= database.column_names("contract_search")
    finally:
        set_database(None)
