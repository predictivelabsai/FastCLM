"""Private, organisation-scoped FastCLM integration API."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from starlette.responses import JSONResponse, RedirectResponse

from fastclm import __version__
from fastclm.config import settings
from fastclm.database import get_database
from fastclm.lifecycle import STATUSES
from fastclm.security import Actor
from fastclm.services.contracts import ContractService

from .api_core import IntegrationContext, ObligationCreate, authorise, authorise_write, error_detail
from .seo import BASE_URL


api = FastAPI(
    title="FastCLM Integration API",
    version=__version__,
    description=(
        "Private, organisation-scoped contract integration API. Contract data is never public.\n\n"
        "All data calls require a bearer token and `X-FastCLM-Organisation`. Selected writes also "
        "require `X-FastCLM-Actor` so permissions and audit attribution remain explicit."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    servers=[{"url": f"{BASE_URL}/api", "description": "Production"}],
    contact={"name": "FastSME", "url": "https://fastsme.com"},
    license_info={"name": "MIT"},
)


@api.exception_handler(HTTPException)
async def api_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": error_detail(exc)}, headers=exc.headers)


def _collection(data: list[dict[str, Any]], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"data": data, "meta": {"total": total, "limit": limit, "offset": offset}}


def _not_found(resource: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "not_found", "message": f"{resource} was not found in this workspace.", "details": {}},
    )


@api.get("/", tags=["System"], operation_id="api_discovery")
def discovery() -> dict[str, Any]:
    return {
        "name": "FastCLM Integration API",
        "version": __version__,
        "access": "private",
        "documentation": f"{settings.public_url}/developers",
        "swagger": f"{settings.public_url}/api/docs",
        "openapi": f"{settings.public_url}/api/openapi.json",
    }


@api.get("/v1/health", tags=["System"], operation_id="api_health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "product": "FastCLM",
        "version": __version__,
        "data_api": "configured" if settings.api_token else "disabled",
        "writes_enabled": bool(settings.api_token),
    }


@api.get("/v1/status", include_in_schema=False)
def legacy_status() -> dict[str, Any]:
    return health()


@api.get("/v1/docs", include_in_schema=False)
def legacy_docs() -> RedirectResponse:
    return RedirectResponse("/api/docs", status_code=307)


@api.get("/v1/redoc", include_in_schema=False)
def legacy_redoc() -> RedirectResponse:
    return RedirectResponse("/api/redoc", status_code=307)


@api.get("/v1/openapi.json", include_in_schema=False)
def legacy_openapi() -> JSONResponse:
    return JSONResponse(api.openapi())


@api.get("/v1/contracts", tags=["Contracts"], operation_id="list_contracts")
def contracts(
    context: IntegrationContext = Depends(authorise),
    contract_status: str = Query(default="", alias="status"),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if contract_status and contract_status not in STATUSES:
        raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "Unknown lifecycle status.", "details": {"status": contract_status}})
    where, params = ["c.organisation_id=?"], [context.organisation_id]
    if contract_status:
        where.append("c.status=?")
        params.append(contract_status)
    if q:
        where.append("(lower(c.title) LIKE ? OR lower(c.reference) LIKE ? OR lower(COALESCE(p.name,'')) LIKE ?)")
        needle = f"%{q.lower()}%"
        params.extend([needle, needle, needle])
    clause = " AND ".join(where)
    db = get_database()
    total = int(db.scalar("SELECT COUNT(*) FROM contracts c LEFT JOIN counterparties p ON p.id=c.counterparty_id WHERE " + clause, params) or 0)
    rows = db.rows(
        "SELECT c.id,c.reference,c.title,c.contract_type,c.jurisdiction,c.status,c.risk_level,c.value_amount,c.currency,c.effective_date,c.expiry_date,c.notice_date,c.renewal_type,p.name counterparty_name "
        "FROM contracts c LEFT JOIN counterparties p ON p.id=c.counterparty_id WHERE " + clause + " ORDER BY c.updated_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return _collection(rows, total, limit, offset)


@api.get("/v1/contracts/{contract_id}", tags=["Contracts"], operation_id="get_contract")
def contract(contract_id: str, context: IntegrationContext = Depends(authorise)) -> dict[str, Any]:
    db = get_database()
    row = db.one("SELECT * FROM contracts WHERE id=? AND organisation_id=?", (contract_id, context.organisation_id))
    if not row:
        raise _not_found("Contract")
    row["versions"] = db.rows(
        "SELECT id,version_number,label,source_filename,media_type,byte_size,checksum,created_at FROM contract_versions WHERE contract_id=? AND organisation_id=? ORDER BY version_number DESC",
        (contract_id, context.organisation_id),
    )
    row["obligations"] = db.rows(
        "SELECT id,title,description,due_date,status,recurrence FROM obligations WHERE contract_id=? AND organisation_id=? ORDER BY due_date",
        (contract_id, context.organisation_id),
    )
    return row


@api.get("/v1/obligations", tags=["Obligations"], operation_id="list_obligations")
def obligations(
    context: IntegrationContext = Depends(authorise),
    obligation_status: str = Query(default="open", alias="status", pattern="^(|open|complete|waived)$"),
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_database()
    where = "o.organisation_id=? AND (?='' OR o.status=?)"
    params = (context.organisation_id, obligation_status, obligation_status)
    total = int(db.scalar("SELECT COUNT(*) FROM obligations o WHERE " + where, params) or 0)
    rows = db.rows(
        "SELECT o.id,o.contract_id,o.title,o.description,o.due_date,o.status,o.recurrence,c.reference,c.title contract_title "
        "FROM obligations o JOIN contracts c ON c.id=o.contract_id WHERE " + where + " ORDER BY o.due_date LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return _collection(rows, total, limit, offset)


@api.post("/v1/obligations", status_code=201, tags=["Obligations"], operation_id="create_obligation")
def create_obligation(payload: ObligationCreate, actor: Actor = Depends(authorise_write)) -> dict[str, Any]:
    try:
        return ContractService().add_obligation(actor, payload.contract_id, payload.model_dump())
    except LookupError as exc:
        raise _not_found("Contract") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": str(exc), "details": {}}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_obligation", "message": str(exc), "details": {}}) from exc


@api.get("/v1/obligations/{obligation_id}", tags=["Obligations"], operation_id="get_obligation")
def obligation(obligation_id: str, context: IntegrationContext = Depends(authorise)) -> dict[str, Any]:
    row = get_database().one(
        "SELECT o.*,c.reference,c.title contract_title FROM obligations o JOIN contracts c ON c.id=o.contract_id WHERE o.id=? AND o.organisation_id=?",
        (obligation_id, context.organisation_id),
    )
    if not row:
        raise _not_found("Obligation")
    return row


@api.get("/v1/counterparties", tags=["Counterparties"], operation_id="list_counterparties")
def counterparties(
    context: IntegrationContext = Depends(authorise),
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_database()
    total = int(db.scalar("SELECT COUNT(*) FROM counterparties WHERE organisation_id=?", (context.organisation_id,)) or 0)
    rows = db.rows(
        "SELECT id,name,registration_number,jurisdiction,contact_name,contact_email,created_at FROM counterparties WHERE organisation_id=? ORDER BY name LIMIT ? OFFSET ?",
        (context.organisation_id, limit, offset),
    )
    return _collection(rows, total, limit, offset)


@api.get("/v1/counterparties/{counterparty_id}", tags=["Counterparties"], operation_id="get_counterparty")
def counterparty(counterparty_id: str, context: IntegrationContext = Depends(authorise)) -> dict[str, Any]:
    row = get_database().one(
        "SELECT * FROM counterparties WHERE id=? AND organisation_id=?", (counterparty_id, context.organisation_id)
    )
    if not row:
        raise _not_found("Counterparty")
    return row
