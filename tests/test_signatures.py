import json
import base64
import hashlib
import hmac
from dataclasses import replace

import pytest

from fastclm.config import settings
from fastclm.services import signatures
from fastclm.services.contracts import ContractService
from fastclm.services.signatures import SignatureService


class Response:
    def __init__(self, data=None, content=b""):
        self.data = data or {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def signature_contract(actor):
    contracts = ContractService()
    contract = contracts.create(actor, {"title": "Signature agreement"})
    contracts.transition(actor, contract["id"], "review")
    contracts.transition(actor, contract["id"], "approval")
    contracts.approve(actor, contract["id"], "approved")
    return contracts, contract


def test_signwell_stub_matches_create_document_shape(workspace):
    actor, _, _ = workspace
    _, contract = signature_contract(actor)
    request = SignatureService().prepare(actor, contract["id"], "signwell", "Casey Smith", "casey@example.test")
    payload = json.loads(request["request_json"])
    assert payload["draft"] is True
    assert payload["recipients"][0]["id"] == "signer_1"
    assert payload["metadata"]["fastclm_contract_id"] == contract["id"]
    assert request["status"] == "configuration_required"


def test_signwell_dispatch_is_human_confirmed_and_completion_is_verified(workspace, fresh_db, monkeypatch, tmp_path):
    actor, _, _ = workspace
    _, contract = signature_contract(actor)
    configured = replace(settings, signwell_api_key="signwell-test", signwell_webhook_token="hook-token", upload_dir=tmp_path / "objects")
    monkeypatch.setattr(signatures, "settings", configured)
    sent_payload = {}

    def post(_url, **kwargs):
        sent_payload.update(kwargs["json"])
        return Response({"id": "signwell-document-1", "status": "Sent"})

    completed_pdf = b"%PDF-1.4\n%%EOF\n"

    def get(url, **_kwargs):
        if url.endswith("/completed_pdf"):
            return Response(content=completed_pdf)
        return Response({
            "id": "signwell-document-1", "status": "Completed",
            "recipients": [{"id": "signer_1", "name": "Casey Smith", "email": "casey@example.test", "status": "completed"}],
        })

    monkeypatch.setattr(signatures.httpx, "post", post)
    monkeypatch.setattr(signatures.httpx, "get", get)
    service = SignatureService()
    request = service.prepare(actor, contract["id"], "signwell", "Casey Smith", "casey@example.test")
    assert fresh_db.scalar("SELECT COUNT(*) FROM signature_events") == 0
    dispatched = service.dispatch(actor, request["id"])
    assert dispatched["status"] == "sent"
    assert sent_payload["draft"] is False
    assert sent_payload["with_signature_page"] is True
    assert base64.b64decode(sent_payload["files"][0]["file_base64"]).startswith(b"%PDF")

    body = json.dumps({
        "event": {"hash": "event-1", "type": "document_completed"},
        "data": {"object": {"id": "signwell-document-1"}},
    }).encode()
    event = service.handle_webhook("signwell", body, {"x-fastclm-signwell-token": "hook-token"})
    assert event["verified"] == 1
    completed, content = service.completed_content(actor, request["id"])
    assert completed["status"] == "completed"
    assert completed["completed_checksum"] == hashlib.sha256(completed_pdf).hexdigest()
    assert content == completed_pdf
    assert fresh_db.scalar("SELECT status FROM signature_recipients WHERE signature_request_id=?", (request["id"],)) == "completed"
    service.handle_webhook("signwell", body, {"x-fastclm-signwell-token": "hook-token"})
    assert fresh_db.scalar("SELECT COUNT(*) FROM signature_events") == 1


def test_docusign_connect_requires_valid_hmac(workspace, monkeypatch, tmp_path):
    actor, _, _ = workspace
    _, contract = signature_contract(actor)
    configured = replace(
        settings,
        docusign_access_token="access-token",
        docusign_account_id="account-1",
        docusign_webhook_secret="webhook-secret",
        upload_dir=tmp_path / "objects",
    )
    monkeypatch.setattr(signatures, "settings", configured)
    monkeypatch.setattr(signatures.httpx, "post", lambda *_args, **_kwargs: Response({"envelopeId": "envelope-1", "status": "sent"}))
    service = SignatureService()
    request = service.prepare(actor, contract["id"], "docusign", "Dana Lee", "dana@example.test")
    service.dispatch(actor, request["id"])
    body = json.dumps({"event": "envelope-delivered", "data": {"envelopeId": "envelope-1", "envelopeSummary": {"envelopeId": "envelope-1", "status": "delivered"}}}).encode()
    with pytest.raises(PermissionError, match="signature"):
        service.handle_webhook("docusign", body, {"x-docusign-signature-1": "invalid"})
    signature = base64.b64encode(hmac.new(b"webhook-secret", body, hashlib.sha256).digest()).decode()
    event = service.handle_webhook("docusign", body, {"X-DocuSign-Signature-1": signature})
    assert event["verified"] == 1
    assert ContractService().get(actor, contract["id"])["signatures"][0]["status"] == "viewed"
