"""Application initialisation and deterministic synthetic demo workspace."""
from __future__ import annotations

from datetime import date, timedelta

from fastclm.database import get_database
from fastclm.security import token
from fastclm.services.contracts import ContractService
from fastclm.services.documents import DocumentService
from fastclm.services.identity import IdentityService
from fastclm.services.assistant import AssistantService


DEMO_EMAIL = "owner@fastclm.example"


def _demo_pdf(lines: list[str]) -> bytes:
    """Build a tiny text-layer PDF without adding a demo-only dependency."""
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    stream = "BT /F1 11 Tf 58 770 Td 15 TL " + " ".join(f"({line}) Tj T*" for line in escaped) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n{obj}\nendobj\n".encode())
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(payload)


def initialize() -> None:
    get_database().migrate()


def ensure_demo() -> tuple[dict, dict]:
    initialize()
    identity = IdentityService()
    db = get_database()
    existing = db.one("SELECT id FROM users WHERE email=?", (DEMO_EMAIL,))
    if existing:
        memberships = identity.memberships(existing["id"])
        return identity.user(existing["id"]), identity.organisation(memberships[0]["organisation_id"])

    user, organisation = identity.create_workspace(DEMO_EMAIL, token() + "Aa1!", "Alex Morgan", "Acme Studio")
    actor = identity.actor(user["id"], organisation["id"])
    service = ContractService()
    northstar = service.add_counterparty(actor, {
        "name": "Northstar Cloud Ltd", "registration_number": "09876543", "jurisdiction": "England and Wales",
        "contact_name": "Sam Taylor", "contact_email": "sam@northstar.example",
    })
    atelier = service.add_counterparty(actor, {
        "name": "Atelier Europa GmbH", "registration_number": "HRB 123456", "jurisdiction": "Germany",
        "contact_name": "Robin Fischer", "contact_email": "robin@atelier.example",
    })
    today = date.today()
    msa = service.create(actor, {
        "title": "Cloud services master agreement", "reference": "CLM-2026-001", "contract_type": "Master services agreement",
        "counterparty_id": northstar["id"], "jurisdiction": "England and Wales", "summary": "Managed cloud hosting and support services.",
        "value_amount": "96000", "currency": "GBP", "effective_date": (today - timedelta(days=180)).isoformat(),
        "expiry_date": (today + timedelta(days=120)).isoformat(), "notice_date": (today + timedelta(days=60)).isoformat(), "renewal_type": "automatic",
    })
    service.add_block(actor, msa["id"], "heading", "1. Services")
    service.add_block(actor, msa["id"], "paragraph", "Northstar will provide managed cloud hosting, monitoring, support, and service reporting under agreed statements of work.")
    service.add_block(actor, msa["id"], "clause", "This agreement automatically renews for successive twelve-month terms unless either party gives sixty days' written notice.")
    service.add_block(actor, msa["id"], "clause", "Liability is capped at fees paid in the preceding twelve months. Neither party has unlimited liability except where mandatory law requires it.")
    service.add_block(actor, msa["id"], "clause", "The parties will comply with UK GDPR and enter Article 28 processor terms where personal data is processed.")
    service.add_block(actor, msa["id"], "clause", "This agreement is governed by the laws of England and Wales. Either party may terminate for material breach after a thirty-day cure period.")
    DocumentService().ingest(actor, msa["id"], "Northstar-Cloud-MSA.pdf", _demo_pdf([
        "NORTHSTAR CLOUD MASTER SERVICES AGREEMENT",
        "Northstar will provide managed cloud hosting, monitoring, support and service reporting.",
        "This agreement automatically renews for successive twelve-month terms unless either party gives sixty days written notice.",
        "Liability is capped at fees paid in the preceding twelve months.",
        "The parties will comply with UK GDPR and enter Article 28 processor terms where personal data is processed.",
        "This agreement is governed by the laws of England and Wales.",
    ]))
    service.transition(actor, msa["id"], "review")
    service.transition(actor, msa["id"], "approval")
    service.approve(actor, msa["id"], "approved", "Commercial and data-protection review complete.")
    service.transition(actor, msa["id"], "active")
    service.add_obligation(actor, msa["id"], {"title": "Quarterly service review", "description": "Review uptime, incidents, and service credits.", "due_date": (today + timedelta(days=12)).isoformat(), "recurrence": "quarterly"})
    service.add_obligation(actor, msa["id"], {"title": "Decide renewal", "description": "Confirm renewal or issue notice before the contractual deadline.", "due_date": (today + timedelta(days=60)).isoformat(), "recurrence": "none"})

    dpa = service.create(actor, {
        "title": "EU data processing agreement", "reference": "CLM-2026-002", "contract_type": "Data processing agreement",
        "counterparty_id": atelier["id"], "jurisdiction": "European Union", "summary": "Processor terms for customer analytics services.",
        "value_amount": "24000", "currency": "EUR", "effective_date": today.isoformat(), "renewal_type": "manual",
    })
    service.add_block(actor, dpa["id"], "clause", "The processor will process personal data only on documented instructions and will notify the controller of subprocessors.")
    service.add_block(actor, dpa["id"], "clause", "The agreement is governed by German law and may be terminated if the main services agreement ends.")
    service.snapshot(actor, dpa["id"], "Internal review draft")
    service.transition(actor, dpa["id"], "review")
    AssistantService().seed_demo(actor, msa["id"])
    return user, organisation
