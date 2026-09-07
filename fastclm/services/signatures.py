"""Provider-neutral electronic-signature request preparation."""
from __future__ import annotations

import json

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.contracts import ContractService
from fastclm.services.identity import new_id, now


class SignatureService:
    def prepare(self, actor: Actor, contract_id: str, provider: str, recipient_name: str, recipient_email: str) -> dict:
        actor.require("contracts.transition")
        contract = ContractService().get(actor, contract_id)
        if contract["status"] != "signature":
            raise ValueError("Move the approved contract to signature before preparing a request")
        provider = provider.strip().lower()
        if provider not in {"docusign", "signwell"}:
            raise ValueError("Supported providers are DocuSign and SignWell")
        if "@" not in recipient_email:
            raise ValueError("A valid recipient email is required")
        latest = contract["versions"][0] if contract["versions"] else None
        if provider == "signwell":
            payload = {
                "draft": True,
                "test_mode": settings.signwell_test_mode,
                "name": contract["title"],
                "subject": f"Please sign {contract['title']}",
                "message": "Please review and sign this agreement.",
                "recipients": [{"id": "signer_1", "name": recipient_name, "email": recipient_email}],
                "metadata": {"fastclm_contract_id": contract_id, "fastclm_reference": contract["reference"]},
                "source_version": latest["version_number"] if latest else None,
            }
        else:
            payload = {
                "status": "created",
                "emailSubject": f"Please sign {contract['title']}",
                "documents": [{"documentId": "1", "name": latest["source_filename"] or f"{contract['reference']}.pdf" if latest else f"{contract['reference']}.pdf"}],
                "recipients": {"signers": [{"recipientId": "1", "name": recipient_name, "email": recipient_email}]},
                "metadata": {"fastclm_contract_id": contract_id},
            }
        request_id, created = new_id(), now()
        configured = bool(settings.signwell_api_key) if provider == "signwell" else False
        status = "ready" if configured else "configuration_required"
        with get_database().transaction() as tx:
            tx.execute("INSERT INTO signature_requests(id,organisation_id,contract_id,provider,recipient_name,recipient_email,status,request_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (request_id, actor.organisation_id, contract_id, provider, recipient_name.strip(), recipient_email.strip().lower(), status, json.dumps(payload), actor.user_id, created, created))
            AuditService().record(actor, "contract", contract_id, "signature.prepared", {"provider": provider, "request_id": request_id, "configured": configured}, tx)
        return get_database().one("SELECT * FROM signature_requests WHERE id=?", (request_id,))
