"""Safe document ingestion and extraction for editable contract blocks."""
from __future__ import annotations

import io
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document

from fastclm.config import settings
from fastclm.security import Actor
from fastclm.services.contracts import ContractService, text_to_blocks
from fastclm.services.identity import new_id
from fastclm.services.malware import scan_document
from fastclm.storage import get_storage


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


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    pages: tuple[str, ...]
    ocr_applied: bool = False


def _ocr_page(page) -> str:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(200 / 72, 200 / 72), alpha=False)
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", settings.ocr_language, "--psm", "6"],
        input=pixmap.tobytes("png"), capture_output=True, timeout=45, check=False,
    )
    if result.returncode != 0:
        raise ValueError("OCR failed for a scanned PDF page")
    return result.stdout.decode("utf-8", errors="replace").strip()


def extract_document(filename: str, content: bytes) -> ExtractionResult:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Upload a PDF, Word .docx, text, or Markdown document")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Document must be between 1 byte and 15 MB")
    if suffix == ".pdf":
        try:
            pdf = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ValueError("The PDF could not be opened") from exc
        pages, used_ocr = [], False
        try:
            for page in pdf:
                text = page.get_text("text").strip()
                if settings.ocr_enabled and len(re.sub(r"\W", "", text)) < 12:
                    ocr_text = _ocr_page(page)
                    if ocr_text:
                        text, used_ocr = ocr_text, True
                pages.append(text)
        finally:
            pdf.close()
        return ExtractionResult("\n\n".join(text for text in pages if text), tuple(pages), used_ocr)
    if suffix == ".docx":
        document = Document(io.BytesIO(content))
        text = "\n\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
        return ExtractionResult(text, (text,))
    text = content.decode("utf-8", errors="replace")
    return ExtractionResult(text, (text,))


def extract_text(filename: str, content: bytes) -> str:
    return extract_document(filename, content).text


class DocumentService:
    def ingest(self, actor: Actor, contract_id: str, filename: str, content: bytes) -> dict:
        clean = safe_filename(filename)
        suffix = Path(clean).suffix.lower()
        if suffix not in ALLOWED:
            raise ValueError("Upload a PDF, Word .docx, text, or Markdown document")
        if not content or len(content) > MAX_BYTES:
            raise ValueError("Document must be between 1 byte and 15 MB")
        scan = scan_document(clean, content, settings)
        extracted = extract_document(clean, content)
        if not extracted.text.strip():
            raise ValueError("No editable text could be extracted from this document")
        relative = str(Path(actor.organisation_id) / contract_id / f"{new_id()}{suffix}")
        storage = get_storage(config=settings)
        storage.put(relative, content, ALLOWED[suffix])
        service = ContractService()
        try:
            service.replace_blocks(actor, contract_id, text_to_blocks(extracted.text))
            return service.snapshot(
                actor, contract_id, f"Imported {clean}", source_filename=clean,
                storage_path=relative, media_type=ALLOWED[suffix], byte_size=len(content),
                source_checksum=hashlib.sha256(content).hexdigest(), storage_backend=storage.name,
                page_text_json=json.dumps(extracted.pages, ensure_ascii=False), ocr_applied=extracted.ocr_applied,
                malware_scan_status=scan.status, malware_scanner=scan.scanner,
            )
        except Exception:
            storage.delete(relative)
            raise
