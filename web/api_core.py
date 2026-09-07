"""Shared primitives for the private FastCLM integration API."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from fastclm.config import settings
from fastclm.database import get_database
from fastclm.security import Actor
from fastclm.services.identity import IdentityService


class PaginationMeta(BaseModel):
    """Offset pagination metadata."""

    total: int
    limit: int
    offset: int


class ObligationCreate(BaseModel):
    """Integration-safe obligation creation request."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    due_date: str = Field(default="", max_length=10)
    recurrence: str = Field(default="none", pattern="^(none|monthly|quarterly|annual)$")


@dataclass(frozen=True)
class IntegrationContext:
    """Authenticated organisation scope carried by an API request."""

    organisation_id: str


bearer = HTTPBearer(
    auto_error=False,
    scheme_name="FastCLM API token",
    description=(
        "All contract data requires `Authorization: Bearer <token>` and an "
        "`X-FastCLM-Organisation` workspace identifier."
    ),
)


def authorise(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
    organisation_id: str = Header(default="", alias="X-FastCLM-Organisation"),
) -> IntegrationContext:
    """Require the deployment token and a real organisation scope."""

    if not settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "api_disabled",
                "message": "The integration API is disabled until FASTCLM_API_TOKEN is configured.",
                "details": {},
            },
        )
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(settings.api_token, supplied):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "A valid bearer token is required.", "details": {}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not organisation_id or not get_database().one(
        "SELECT id FROM organisations WHERE id=?", (organisation_id,)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_organisation",
                "message": "A valid X-FastCLM-Organisation header is required.",
                "details": {},
            },
        )
    return IntegrationContext(organisation_id)


def authorise_write(
    context: IntegrationContext = Security(authorise),  # noqa: B008
    actor_user_id: str = Header(default="", alias="X-FastCLM-Actor"),
) -> Actor:
    """Require a workspace member to attribute and authorise an API mutation."""

    if not actor_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "actor_required",
                "message": "X-FastCLM-Actor must identify a member authorised for this write.",
                "details": {},
            },
        )
    try:
        return IdentityService().actor(actor_user_id, context.organisation_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_actor",
                "message": "The API actor is not a member of this workspace.",
                "details": {},
            },
        ) from exc


def error_detail(exc: HTTPException) -> dict[str, Any]:
    """Normalise framework and application errors into one envelope."""

    if isinstance(exc.detail, dict):
        return exc.detail
    return {"code": "http_error", "message": str(exc.detail), "details": {}}


def write_swagger(api, destination: str | Path) -> None:
    """Write the deterministic compatibility OpenAPI snapshot."""

    Path(destination).write_text(json.dumps(api.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
