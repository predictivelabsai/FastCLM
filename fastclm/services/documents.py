"""Safe document ingestion and extraction for editable contract blocks."""
from __future__ import annotations

import io
import hashlib
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from fastclm.config import settings
from fastclm.security import Actor
from fastclm.services.contracts import ContractService, text_to_blocks
from fastclm.services.identity import new_id


ALLOWED = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain", ".md": "text/markdown"}
MAX_BYTES = 15 * 1024 * 1024


def safe_filename(value: str) -> str:
    name = Path(value or "contract").name
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name)[:180]


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Upload a PDF, Word .docx, text, or Markdown document")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Document must be between 1 byte and 15 MB")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages if (page.extract_text() or "").strip())
    if suffix == ".docx":
        document = Document(io.BytesIO(content))
        return "\n\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
    return content.decode("utf-8", errors="replace")


class DocumentService:
    def ingest(self, actor: Actor, contract_id: str, filename: str, content: bytes) -> dict:
        clean = safe_filename(filename)
        suffix = Path(clean).suffix.lower()
        text = extract_text(clean, content)
        if not text.strip():
            raise ValueError("No editable text could be extracted from this document")
        relative = Path(actor.organisation_id) / contract_id / f"{new_id()}{suffix}"
        target = settings.upload_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        service = ContractService()
        service.replace_blocks(actor, contract_id, text_to_blocks(text))
        return service.snapshot(
            actor, contract_id, f"Imported {clean}", source_filename=clean,
            storage_path=str(relative), media_type=ALLOWED[suffix], byte_size=len(content),
            source_checksum=hashlib.sha256(content).hexdigest(),
        )
