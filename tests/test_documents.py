from dataclasses import replace

import pytest

from fastclm.config import settings
from fastclm.services import documents
from fastclm.services.contracts import ContractService
from fastclm.services.documents import DocumentService, extract_text, safe_filename


def test_text_document_ingestion_creates_blocks_attachment_and_version(workspace, tmp_path, monkeypatch):
    actor, _, _ = workspace
    service = ContractService()
    contract = service.create(actor, {"title": "Uploaded agreement"})
    monkeypatch.setattr(documents, "settings", replace(settings, upload_dir=tmp_path / "uploads"))
    result = DocumentService().ingest(actor, contract["id"], "../Agreement.txt", b"1. SERVICES:\n\nThe supplier provides support.\n\nTermination is on 30 days notice.")
    item = service.get(actor, contract["id"])
    assert result["source_filename"] == "Agreement.txt"
    assert result["version_number"] == 2
    assert len(item["blocks"]) == 3
    assert (tmp_path / "uploads" / result["storage_path"]).is_file()


def test_document_rejects_unsupported_or_empty_files():
    with pytest.raises(ValueError):
        extract_text("agreement.exe", b"not a contract")
    with pytest.raises(ValueError):
        extract_text("agreement.txt", b"")
    assert safe_filename("../../client/nda?.pdf") == "nda_.pdf"
