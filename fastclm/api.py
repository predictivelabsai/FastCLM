"""Token-gated FastAPI integration surface."""
from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from fastclm import __version__
from fastclm.config import settings
from fastclm.database import get_database


api = FastAPI(
    title="FastCLM Integration API",
    version=__version__,
    description="Private, organisation-scoped read API for contract integrations. Contract data is never public.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


def authorise(
    authorization: str = Header(default=""),
    organisation_id: str = Header(default="", alias="X-FastCLM-Organisation"),
) -> str:
    if not settings.api_token:
        raise HTTPException(status_code=503, detail="Integration API is not configured")
    expected = f"Bearer {settings.api_token}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    if not organisation_id or not get_database().one("SELECT id FROM organisations WHERE id=?", (organisation_id,)):
        raise HTTPException(status_code=403, detail="A valid organisation header is required")
    return organisation_id


@api.get("/status", tags=["System"])
def status():
    return {"status": "ok", "product": "FastCLM", "version": __version__, "data_api": "configured" if settings.api_token else "disabled"}


@api.get("/contracts", tags=["Contracts"])
def contracts(
    organisation_id: str = Depends(authorise),
    status: str = Query(default=""),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
):
    where, params = ["c.organisation_id=?"], [organisation_id]
    if status:
        where.append("c.status=?")
        params.append(status)
    if q:
        where.append("(lower(c.title) LIKE ? OR lower(c.reference) LIKE ? OR lower(COALESCE(p.name,'')) LIKE ?)")
        needle = f"%{q.lower()}%"
        params.extend([needle, needle, needle])
    rows = get_database().rows(
        "SELECT c.id,c.reference,c.title,c.contract_type,c.jurisdiction,c.status,c.risk_level,c.value_amount,c.currency,c.effective_date,c.expiry_date,c.notice_date,c.renewal_type,p.name counterparty_name "
        "FROM contracts c LEFT JOIN counterparties p ON p.id=c.counterparty_id WHERE " + " AND ".join(where) + " ORDER BY c.updated_at DESC LIMIT ?",
        [*params, limit],
    )
    return {"data": rows, "count": len(rows)}


@api.get("/contracts/{contract_id}", tags=["Contracts"])
def contract(contract_id: str, organisation_id: str = Depends(authorise)):
    row = get_database().one("SELECT * FROM contracts WHERE id=? AND organisation_id=?", (contract_id, organisation_id))
    if not row:
        raise HTTPException(status_code=404, detail="Contract not found")
    row["versions"] = get_database().rows("SELECT id,version_number,label,source_filename,media_type,byte_size,checksum,created_at FROM contract_versions WHERE contract_id=? AND organisation_id=? ORDER BY version_number DESC", (contract_id, organisation_id))
    row["obligations"] = get_database().rows("SELECT id,title,description,due_date,status,recurrence FROM obligations WHERE contract_id=? AND organisation_id=? ORDER BY due_date", (contract_id, organisation_id))
    return row


@api.get("/obligations", tags=["Obligations"])
def obligations(organisation_id: str = Depends(authorise), status: str = Query(default="open"), limit: int = Query(default=100, ge=1, le=250)):
    rows = get_database().rows("SELECT o.id,o.contract_id,o.title,o.description,o.due_date,o.status,o.recurrence,c.reference,c.title contract_title FROM obligations o JOIN contracts c ON c.id=o.contract_id WHERE o.organisation_id=? AND (?='' OR o.status=?) ORDER BY o.due_date LIMIT ?", (organisation_id, status, status, limit))
    return {"data": rows, "count": len(rows)}


@api.get("/counterparties", tags=["Counterparties"])
def counterparties(organisation_id: str = Depends(authorise), limit: int = Query(default=100, ge=1, le=250)):
    rows = get_database().rows("SELECT id,name,registration_number,jurisdiction,contact_name,contact_email,created_at FROM counterparties WHERE organisation_id=? ORDER BY name LIMIT ?", (organisation_id, limit))
    return {"data": rows, "count": len(rows)}
