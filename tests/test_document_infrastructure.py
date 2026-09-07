from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pymupdf
import pytest

from fastclm.config import settings
from fastclm.services import backups, documents, retention
from fastclm.services.backups import BackupService, decrypt_backup
from fastclm.services.contracts import ContractService
from fastclm.services.documents import DocumentService, extract_document
from fastclm.services.malware import UnsafeDocument, scan_document
from fastclm.services.retention import RetentionService
from fastclm.storage import LocalStorage, safe_object_key


def test_builtin_scanner_rejects_malware_active_pdf_and_mismatched_content():
    with pytest.raises(UnsafeDocument, match="antivirus"):
        scan_document("agreement.txt", b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE")
    with pytest.raises(UnsafeDocument, match="active"):
        scan_document("agreement.pdf", b"%PDF-1.4\n1 0 obj << /JavaScript 2 0 R >>")
    with pytest.raises(UnsafeDocument, match="does not match"):
        scan_document("agreement.docx", b"not a zip")


def test_scanned_pdf_uses_page_ocr_and_preserves_page_provenance(monkeypatch):
    source = pymupdf.open()
    source.new_page()
    content = source.tobytes()
    source.close()
    monkeypatch.setattr(documents, "_ocr_page", lambda _page: "Scanned termination clause")
    result = extract_document("scan.pdf", content)
    assert result.text == "Scanned termination clause"
    assert result.pages == ("Scanned termination clause",)
    assert result.ocr_applied is True


def test_local_object_storage_rejects_traversal_and_round_trips(tmp_path):
    store = LocalStorage(tmp_path / "objects")
    store.put("org/contract/source.txt", b"contract", "text/plain")
    assert store.exists("org/contract/source.txt")
    assert store.get("org/contract/source.txt") == b"contract"
    assert store.delete("org/contract/source.txt") is True
    assert store.delete("org/contract/source.txt") is False
    with pytest.raises(ValueError):
        safe_object_key("../escape")


def test_retention_is_opt_in_tenant_scoped_and_preserves_version_metadata(workspace, tmp_path, monkeypatch):
    actor, _, _ = workspace
    configured = replace(settings, upload_dir=tmp_path / "objects")
    monkeypatch.setattr(documents, "settings", configured)
    monkeypatch.setattr(retention, "settings", configured)
    contract = ContractService().create(actor, {"title": "Expired terms"})
    version = DocumentService().ingest(actor, contract["id"], "terms.txt", b"Terms retained as immutable text.")
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with retention.get_database().transaction() as tx:
        tx.execute("UPDATE contracts SET status='expired' WHERE id=?", (contract["id"],))
        tx.execute("UPDATE contract_versions SET created_at=? WHERE id=?", (old, version["id"]))
    assert RetentionService().run(actor.organisation_id, actor)["purged"] == 0
    RetentionService().set_policy(actor, True, 30)
    assert RetentionService().run(actor.organisation_id, actor) == {"purged": 1, "already_missing": 0}
    retained = retention.get_database().one("SELECT * FROM contract_versions WHERE id=?", (version["id"],))
    assert retained["body_text"] == "Terms retained as immutable text."
    assert retained["source_checksum"] == version["source_checksum"]
    assert retained["attachment_purged_at"]
    assert not LocalStorage(configured.upload_dir).exists(version["storage_path"])


def test_backup_is_tenant_scoped_encrypted_and_contains_verified_attachment(workspace, tmp_path, monkeypatch):
    actor, _, _ = workspace
    configured = replace(settings, upload_dir=tmp_path / "objects", secret="backup-test-secret")
    monkeypatch.setattr(documents, "settings", configured)
    monkeypatch.setattr(backups, "settings", configured)
    contract = ContractService().create(actor, {"title": "Backup terms"})
    version = DocumentService().ingest(actor, contract["id"], "terms.txt", b"Confidential source terms.")
    item = BackupService().create(actor)
    encrypted = LocalStorage(configured.upload_dir).get(item["storage_path"])
    assert b"Confidential source terms" not in encrypted
    archive_bytes = decrypt_backup(encrypted)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        records = json.loads(archive.read("records.json"))
        assert manifest["organisation_id"] == actor.organisation_id
        assert any(row["id"] == contract["id"] for row in records["contracts"])
        assert archive.read(f"attachments/{version['id']}/terms.txt") == b"Confidential source terms."
    _item, downloaded = BackupService().content(actor, item["id"])
    assert downloaded == encrypted
