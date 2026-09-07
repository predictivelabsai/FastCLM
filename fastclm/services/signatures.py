"""Human-confirmed e-signature dispatch, status, and evidence handling."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pymupdf
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.audit import AuditService
from fastclm.services.contracts import ContractService
from fastclm.services.identity import new_id, now
from fastclm.services.malware import scan_document
from fastclm.storage import get_storage


MAX_WEBHOOK_BYTES = 2 * 1024 * 1024
MAX_COMPLETED_BYTES = 50 * 1024 * 1024


class SignatureService:
    def _request(self, actor: Actor, request_id: str) -> dict:
        actor.require("contracts.view")
        row = get_database().one(
            "SELECT s.*,c.reference,c.title contract_title FROM signature_requests s "
            "JOIN contracts c ON c.id=s.contract_id WHERE s.id=? AND s.organisation_id=?",
            (request_id, actor.organisation_id),
        )
        if not row:
            raise LookupError("Signature request not found")
        return row

    def prepare(self, actor: Actor, contract_id: str, provider: str, recipient_name: str, recipient_email: str) -> dict:
        actor.require("contracts.transition")
        contract = ContractService().get(actor, contract_id)
        if contract["status"] != "signature":
            raise ValueError("Move the approved contract to signature before preparing a request")
        provider = provider.strip().lower()
        if provider not in {"docusign", "signwell"}:
            raise ValueError("Supported providers are DocuSign and SignWell")
        if not recipient_name.strip() or "@" not in recipient_email:
            raise ValueError("A signer name and valid email are required")
        latest = contract["versions"][0] if contract["versions"] else None
        if not latest:
            raise ValueError("Save a contract version before preparing a signature request")
        payload = {
            "draft": True, "provider": provider, "name": contract["title"],
            "subject": f"Please sign {contract['title']}", "message": "Please review and sign this agreement.",
            "recipients": [{"id": "signer_1", "name": recipient_name.strip(), "email": recipient_email.strip().lower()}],
            "metadata": {"fastclm_contract_id": contract_id, "fastclm_reference": contract["reference"]},
            "source_version_id": latest["id"], "source_version": latest["version_number"],
            "test_mode": settings.signwell_test_mode if provider == "signwell" else None,
        }
        request_id, created = new_id(), now()
        configured = self.configured(provider)
        status = "draft_ready" if configured else "configuration_required"
        with get_database().transaction() as tx:
            tx.execute(
                "INSERT INTO signature_requests(id,organisation_id,contract_id,provider,recipient_name,recipient_email,status,request_json,created_by,created_at,updated_at,source_version_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (request_id, actor.organisation_id, contract_id, provider, recipient_name.strip(), recipient_email.strip().lower(), status, json.dumps(payload, sort_keys=True), actor.user_id, created, created, latest["id"]),
            )
            AuditService().record(actor, "contract", contract_id, "signature.prepared", {"provider": provider, "request_id": request_id, "configured": configured, "source_version_id": latest["id"]}, tx)
        return get_database().one("SELECT * FROM signature_requests WHERE id=?", (request_id,))

    def configured(self, provider: str) -> bool:
        if provider == "signwell":
            return bool(settings.signwell_api_key)
        jwt_ready = settings.docusign_integration_key and settings.docusign_user_id and settings.docusign_private_key
        return bool(settings.docusign_account_id and (settings.docusign_access_token or jwt_ready))

    def _docusign_token(self) -> str:
        if settings.docusign_access_token:
            return settings.docusign_access_token
        issued = int(time.time())
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        header = encode(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
        claims = encode(json.dumps({
            "iss": settings.docusign_integration_key, "sub": settings.docusign_user_id,
            "aud": settings.docusign_oauth_base_url.split("://", 1)[-1],
            "iat": issued, "exp": issued + 3600, "scope": "signature impersonation",
        }, separators=(",", ":")).encode())
        signing_input = f"{header}.{claims}".encode()
        private_key = serialization.load_pem_private_key(settings.docusign_private_key.replace("\\n", "\n").encode(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        assertion = f"{header}.{claims}.{encode(signature)}"
        response = httpx.post(
            f"{settings.docusign_oauth_base_url}/oauth/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}, timeout=30,
        )
        response.raise_for_status()
        token = str(response.json().get("access_token", ""))
        if not token:
            raise RuntimeError("DocuSign OAuth did not return an access token")
        return token

    def _source(self, request: dict) -> tuple[str, str, bytes]:
        version = get_database().one(
            "SELECT * FROM contract_versions WHERE id=? AND contract_id=? AND organisation_id=?",
            (request["source_version_id"], request["contract_id"], request["organisation_id"]),
        )
        if not version:
            raise LookupError("Frozen source version not found")
        if version["storage_path"] and not version.get("attachment_purged_at"):
            content = get_storage(version.get("storage_backend") or "local", settings).get(version["storage_path"])
            expected = version.get("source_checksum") or ""
            if expected and not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected):
                raise ValueError("Frozen source version failed its integrity check")
            return version["source_filename"] or "contract.pdf", version["media_type"] or "application/octet-stream", content
        document = pymupdf.open()
        text = version["body_text"] or "Contract"
        for chunk in ([text[index:index + 2800] for index in range(0, len(text), 2800)] or ["Contract"]):
            page = document.new_page()
            page.insert_textbox(pymupdf.Rect(54, 54, 558, 738), chunk, fontsize=10)
        content = document.tobytes()
        document.close()
        return f"{request['reference']}.pdf", "application/pdf", content

    def dispatch(self, actor: Actor, request_id: str) -> dict:
        actor.require("contracts.transition")
        request = self._request(actor, request_id)
        if request["status"] not in {"draft_ready", "configuration_required"}:
            raise ValueError("Only an unsent draft can be dispatched")
        if not self.configured(request["provider"]):
            raise RuntimeError(f"{request['provider'].title()} is not configured")
        filename, _media_type, content = self._source(request)
        draft, started = json.loads(request["request_json"]), now()
        with get_database().transaction() as tx:
            tx.execute("UPDATE signature_requests SET status='dispatching',dispatch_confirmed_by=?,updated_at=? WHERE id=? AND organisation_id=?", (actor.user_id, started, request_id, actor.organisation_id))
            AuditService().record(actor, "signature_request", request_id, "signature.dispatch.confirmed", {"provider": request["provider"], "source_version_id": request["source_version_id"]}, tx)
        try:
            response = self._send(request["provider"], draft, filename, content)
            external_id = str(response.get("id") or response.get("envelopeId") or "").strip()
            if not external_id:
                raise RuntimeError("Signature provider did not return a document identifier")
            dispatched = now()
            with get_database().transaction() as tx:
                tx.execute("UPDATE signature_requests SET external_id=?,status='sent',response_json=?,dispatched_at=?,updated_at=? WHERE id=? AND organisation_id=?", (external_id, json.dumps(response, sort_keys=True), dispatched, dispatched, request_id, actor.organisation_id))
                tx.execute("INSERT INTO signature_recipients(id,organisation_id,signature_request_id,provider_recipient_id,name,email,status,updated_at) VALUES (?,?,?,?,?,?, 'sent',?)", (new_id(), actor.organisation_id, request_id, "signer_1", request["recipient_name"], request["recipient_email"], dispatched))
                AuditService().record(actor, "signature_request", request_id, "signature.dispatched", {"provider": request["provider"], "external_id": external_id}, tx)
        except Exception as exc:
            with get_database().transaction() as tx:
                tx.execute("UPDATE signature_requests SET status='dispatch_unknown',response_json=?,updated_at=? WHERE id=? AND organisation_id=?", (json.dumps({"error": type(exc).__name__, "message": str(exc)}), now(), request_id, actor.organisation_id))
                AuditService().record(actor, "signature_request", request_id, "signature.dispatch.uncertain", {"provider": request["provider"], "error": type(exc).__name__}, tx)
            raise RuntimeError("Provider dispatch did not complete reliably; reconcile before retrying") from exc
        return self._request(actor, request_id)

    def _send(self, provider: str, draft: dict, filename: str, content: bytes) -> dict:
        encoded, recipient = base64.b64encode(content).decode(), draft["recipients"][0]
        if provider == "signwell":
            payload = {
                "test_mode": settings.signwell_test_mode, "name": draft["name"], "subject": draft["subject"], "message": draft["message"],
                "files": [{"name": filename, "file_base64": encoded}], "recipients": [recipient], "draft": False,
                "with_signature_page": True, "metadata": draft["metadata"],
            }
            response = httpx.post(f"{settings.signwell_api_base_url}/documents", headers={"X-Api-Key": settings.signwell_api_key, "Content-Type": "application/json"}, json=payload, timeout=60)
        else:
            payload = {
                "emailSubject": draft["subject"],
                "documents": [{"documentBase64": encoded, "documentId": "1", "fileExtension": Path(filename).suffix.lstrip(".") or "pdf", "name": filename}],
                "recipients": {"signers": [{"recipientId": "signer_1", "name": recipient["name"], "email": recipient["email"], "tabs": {"signHereTabs": [{"documentId": "1", "pageNumber": "1", "xPosition": "390", "yPosition": "690"}]}}]},
                "eventNotification": {"url": f"{settings.public_url}/webhooks/docusign", "requireAcknowledgment": "true", "loggingEnabled": "true", "includeHMAC": "true", "envelopeEvents": [{"envelopeEventStatusCode": value} for value in ("sent", "delivered", "completed", "declined", "voided")]},
                "status": "sent",
            }
            response = httpx.post(f"{settings.docusign_api_base_url}/v2.1/accounts/{settings.docusign_account_id}/envelopes", headers={"Authorization": f"Bearer {self._docusign_token()}", "Content-Type": "application/json"}, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()

    def handle_webhook(self, provider: str, content: bytes, headers: dict[str, str]) -> dict:
        if len(content) > MAX_WEBHOOK_BYTES:
            raise ValueError("Webhook payload is too large")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Webhook payload must be JSON") from exc
        if provider == "signwell":
            return self._signwell_event(content, payload, {key.lower(): value for key, value in headers.items()})
        if provider == "docusign":
            return self._docusign_event(content, payload, {key.lower(): value for key, value in headers.items()})
        raise ValueError("Unsupported signature provider")

    def _signwell_event(self, content: bytes, payload: dict, headers: dict[str, str]) -> dict:
        event = payload.get("event") or {}
        document = (payload.get("data") or {}).get("object") or {}
        external_id, event_id, event_type = str(document.get("id", "")), str(event.get("hash", "")), str(event.get("type", ""))
        supplied_token = headers.get("x-fastclm-signwell-token", "")
        if not settings.signwell_webhook_token or not hmac.compare_digest(str(supplied_token), settings.signwell_webhook_token):
            raise PermissionError("SignWell webhook token is invalid")
        if not external_id or not event_id or not event_type or not settings.signwell_api_key:
            raise PermissionError("SignWell webhook could not be verified")
        request = get_database().one("SELECT * FROM signature_requests WHERE provider='signwell' AND external_id=?", (external_id,))
        if not request:
            raise LookupError("Signature request not found")
        authoritative = httpx.get(f"{settings.signwell_api_base_url}/documents/{external_id}", headers={"X-Api-Key": settings.signwell_api_key}, timeout=30)
        authoritative.raise_for_status()
        verified_document = authoritative.json()
        if str(verified_document.get("id", "")) != external_id:
            raise PermissionError("SignWell document verification failed")
        return self._record_event(request, event_id, event_type, content, verified_document, event, self._status("", verified_document))

    def _docusign_event(self, content: bytes, payload: dict, headers: dict[str, str]) -> dict:
        supplied = headers.get("x-docusign-signature-1", "")
        if not settings.docusign_webhook_secret or not supplied:
            raise PermissionError("DocuSign webhook signature is required")
        expected = base64.b64encode(hmac.new(settings.docusign_webhook_secret.encode(), content, hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(supplied, expected):
            raise PermissionError("DocuSign webhook signature is invalid")
        data = payload.get("data") or {}
        summary = data.get("envelopeSummary") or payload
        external_id = str(data.get("envelopeId") or summary.get("envelopeId") or "")
        event_type = str(payload.get("event") or summary.get("status") or "envelope-updated")
        request = get_database().one("SELECT * FROM signature_requests WHERE provider='docusign' AND external_id=?", (external_id,))
        if not request:
            raise LookupError("Signature request not found")
        event_id = str(payload.get("retryCount", "0")) + ":" + hashlib.sha256(content).hexdigest()
        return self._record_event(request, event_id, event_type, content, summary, {})

    def _record_event(self, request: dict, event_id: str, event_type: str, content: bytes, document: dict, event: dict, status_override: str = "") -> dict:
        db = get_database()
        existing = db.one("SELECT * FROM signature_events WHERE provider=? AND external_event_id=?", (request["provider"], event_id))
        if existing:
            current = db.one("SELECT * FROM signature_requests WHERE id=?", (request["id"],))
            if current and current["status"] == "completed_document_pending":
                self._retrieve_completed(current)
            return existing
        received, status, event_row_id = now(), status_override or self._status(event_type, document), new_id()
        safe_payload = json.dumps({"event": event, "document": document}, sort_keys=True)
        with db.transaction() as tx:
            tx.execute("INSERT INTO signature_events(id,organisation_id,signature_request_id,provider,external_event_id,event_type,verified,payload_sha256,payload_json,received_at) VALUES (?,?,?,?,?,?,1,?,?,?)", (event_row_id, request["organisation_id"], request["id"], request["provider"], event_id, event_type, hashlib.sha256(content).hexdigest(), safe_payload, received))
            tx.execute("UPDATE signature_requests SET status=?,webhook_verified_at=?,updated_at=? WHERE id=? AND organisation_id=?", (status, received, received, request["id"], request["organisation_id"]))
            self._upsert_recipients(tx, request, document, event, status, received)
            self._external_audit(tx, request, "signature.webhook.verified", {"event_type": event_type, "event_id": event_id, "status": status})
        if status == "completed":
            try:
                self._retrieve_completed({**request, "status": status})
            except Exception:
                with db.transaction() as tx:
                    tx.execute("UPDATE signature_requests SET status='completed_document_pending',updated_at=? WHERE id=?", (now(), request["id"]))
                    self._external_audit(tx, request, "signature.completed_document.pending", {})
                raise
        return db.one("SELECT * FROM signature_events WHERE id=?", (event_row_id,))

    def _status(self, event_type: str, document: dict) -> str:
        value = f"{event_type} {document.get('status', '')}".lower()
        for needle, status in (("completed", "completed"), ("declined", "declined"), ("expired", "expired"), ("canceled", "canceled"), ("cancelled", "canceled"), ("voided", "canceled"), ("error", "error"), ("signed", "in_progress"), ("progress", "in_progress"), ("pending", "in_progress"), ("viewed", "viewed"), ("delivered", "viewed"), ("sent", "sent")):
            if needle in value:
                return status
        return "sent"

    def _upsert_recipients(self, tx, request: dict, document: dict, event: dict, request_status: str, updated: str) -> None:
        recipients = document.get("recipients") or []
        if isinstance(recipients, dict):
            recipients = recipients.get("signers") or []
        related = event.get("related_signer") or {}
        for index, recipient in enumerate(recipients, 1):
            provider_id = str(recipient.get("id") or recipient.get("recipientId") or index)
            email = str(recipient.get("email", "")).lower()
            recipient_status = str(recipient.get("status") or request_status).lower()
            signed_at = str(recipient.get("signed_at") or recipient.get("signedDateTime") or "")
            if related and str(related.get("email", "")).lower() == email and "signed" in str(event.get("type", "")):
                recipient_status, signed_at = "signed", updated
            tx.execute(
                "INSERT INTO signature_recipients(id,organisation_id,signature_request_id,provider_recipient_id,name,email,status,signed_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(signature_request_id,provider_recipient_id) DO UPDATE SET name=excluded.name,email=excluded.email,status=excluded.status,signed_at=CASE WHEN excluded.signed_at='' THEN signature_recipients.signed_at ELSE excluded.signed_at END,updated_at=excluded.updated_at",
                (new_id(), request["organisation_id"], request["id"], provider_id, str(recipient.get("name", "")), email, recipient_status, signed_at, updated),
            )

    def _retrieve_completed(self, request: dict) -> None:
        if request["provider"] == "signwell":
            response = httpx.get(f"{settings.signwell_api_base_url}/documents/{request['external_id']}/completed_pdf", headers={"X-Api-Key": settings.signwell_api_key}, params={"audit_page": "true", "file_format": "pdf"}, timeout=60)
        else:
            response = httpx.get(f"{settings.docusign_api_base_url}/v2.1/accounts/{settings.docusign_account_id}/envelopes/{request['external_id']}/documents/combined", headers={"Authorization": f"Bearer {self._docusign_token()}"}, timeout=60)
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF") or len(content) > MAX_COMPLETED_BYTES:
            raise ValueError("Completed provider document is not a valid bounded PDF")
        scan_document("completed-agreement.pdf", content, settings)
        storage = get_storage(config=settings)
        storage_path = f"{request['organisation_id']}/{request['contract_id']}/signatures/{request['id']}.pdf"
        storage.put(storage_path, content, "application/pdf")
        checksum, completed = hashlib.sha256(content).hexdigest(), now()
        try:
            with get_database().transaction() as tx:
                tx.execute("UPDATE signature_requests SET status='completed',completed_at=?,completed_storage_backend=?,completed_storage_path=?,completed_checksum=?,completed_media_type='application/pdf',updated_at=? WHERE id=? AND organisation_id=?", (completed, storage.name, storage_path, checksum, completed, request["id"], request["organisation_id"]))
                self._external_audit(tx, request, "signature.completed_document.stored", {"checksum": checksum, "storage_backend": storage.name})
        except Exception:
            storage.delete(storage_path)
            raise

    def _external_audit(self, tx, request: dict, action: str, detail: dict) -> None:
        tx.execute("INSERT INTO audit_events(id,organisation_id,actor_user_id,entity_type,entity_id,action,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?)", (new_id(), request["organisation_id"], request.get("created_by"), "signature_request", request["id"], action, json.dumps(detail, sort_keys=True), now()))

    def completed_content(self, actor: Actor, request_id: str) -> tuple[dict, bytes]:
        request = self._request(actor, request_id)
        if not request["completed_storage_path"]:
            raise LookupError("Completed document is not available")
        content = get_storage(request["completed_storage_backend"], settings).get(request["completed_storage_path"])
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), request["completed_checksum"]):
            raise ValueError("Completed document integrity check failed")
        return request, content
