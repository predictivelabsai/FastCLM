"""FastCLM FastHTML entry point and browser routes."""
from __future__ import annotations

import json
import hmac
import re
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import *
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from fastclm import __version__
from fastclm.auth import google_authorize_url, google_enabled, google_exchange
from fastclm.bootstrap import ensure_demo, initialize
from fastclm.config import settings
from fastclm.database import get_database
from fastclm.emailer import send_account_action
from fastclm.reminders import start_scheduler, stop_scheduler
from fastclm.security import Actor, csrf_valid, token
from fastclm.services.audit import AuditService
from fastclm.services.assistant import AssistantService, find_word_range
from fastclm.services.contracts import ContractService
from fastclm.services.credentials import clear_xai_key, key_status, store_xai_key, usage
from fastclm.services.documents import DocumentService, file_checksum
from fastclm.services.identity import IdentityService
from fastclm.services.review import ReviewService
from fastclm.services.scim import ERROR_SCHEMA, SCIMError, SCIMService, USER_SCHEMA
from fastclm.services.signatures import SignatureService
from fastclm.services.skills import SkillService
from fastclm.web.ui import (
    audit_page,
    assistant_page,
    auth_page,
    clauses_page,
    contract_detail_page,
    contract_new_page,
    contracts_page,
    counterparties_page,
    dashboard_page,
    obligations_page,
    settings_page,
    skill_detail_page,
    skills_page,
    invitation_page,
    team_page,
    recovery_page,
)
from web.api import api
from web.developer import developer_page
from web.landing import landing_page
from web.seo import register_seo_routes


app, rt = fast_app(
    live=False,
    pico=False,
    secret_key=settings.secret,
    max_age=8 * 60 * 60,
    same_site="lax",
    sess_https_only=settings.public_url.startswith("https://"),
)
app.mount("/static", StaticFiles(directory=settings.root / "static"), name="static")
app.mount("/api", api)


async def _favicon(_request):
    return FileResponse(settings.root / "static" / "favicon.svg", media_type="image/svg+xml")


# FastHTML registers its extension-based static fallback before application
# routes, so the conventional browser favicon path must precede that fallback.
app.routes.insert(2, Route("/favicon.ico", _favicon, methods=["GET", "HEAD"]))


@app.on_event("startup")
async def startup() -> None:
    initialize()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_scheduler()


def _login(session: dict, user: dict, organisation: dict) -> None:
    session.clear()
    session["auth"] = {"user_id": user["id"], "organisation_id": organisation["id"]}
    session["csrf_token"] = token()


def _actor(request) -> Actor | None:
    auth = request.session.get("auth")
    if not auth:
        return None
    try:
        return IdentityService().actor(auth["user_id"], auth["organisation_id"])
    except (LookupError, PermissionError):
        request.session.clear()
        return None


def _required(request, permission: str | None = None) -> Actor | Response:
    actor = _actor(request)
    if not actor:
        return RedirectResponse(f"/login?next={quote(request.url.path, safe='')}", status_code=303)
    if permission and not actor.can(permission):
        return PlainTextResponse("Forbidden", status_code=403)
    return actor


async def _form(request, permission: str | None = None):
    actor = _required(request, permission)
    if isinstance(actor, Response):
        return actor, None
    data = await request.form()
    if not csrf_valid(request.session, str(data.get("csrf", "")) or request.headers.get("x-csrf-token")):
        return PlainTextResponse("Invalid CSRF token", status_code=403), None
    return actor, data


def _contract_page(request, contract_id: str, notice: str = ""):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    service = ContractService()
    try:
        contract = service.get(actor, contract_id)
    except LookupError:
        return PlainTextResponse("Contract not found", status_code=404)
    return contract_detail_page(
        actor,
        contract,
        service.counterparties(actor),
        request.session["csrf_token"],
        usage(actor.user_id),
        notice,
    )


def _scim_response(data: dict, status_code: int = 200, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(data, status_code=status_code, headers=headers, media_type="application/scim+json")


def _scim_error(exc: SCIMError | str, status_code: int = 400, scim_type: str = "invalidValue") -> JSONResponse:
    if isinstance(exc, SCIMError):
        status_code, scim_type, detail = exc.status, exc.scim_type, str(exc)
    else:
        detail = str(exc)
    return _scim_response({"schemas": [ERROR_SCHEMA], "status": str(status_code), "scimType": scim_type, "detail": detail}, status_code)


def _scim_organisation(request) -> tuple[str, None] | tuple[None, JSONResponse]:
    if not settings.scim_token:
        return None, _scim_error("SCIM provisioning is not configured", 503)
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {settings.scim_token}"
    if not hmac.compare_digest(supplied, expected):
        return None, _scim_error("A valid bearer token is required", 401, "invalidToken")
    organisation_id = request.headers.get("x-fastclm-organisation", "").strip()
    if not get_database().one("SELECT id FROM organisations WHERE id=?", (organisation_id,)):
        return None, _scim_error("A valid X-FastCLM-Organisation header is required", 400)
    return organisation_id, None


@rt("/")
def home(request):
    return RedirectResponse("/app", status_code=303) if _actor(request) else landing_page()


@rt("/login", methods=["GET"])
def login_form(error: str = "", notice: str = ""):
    messages = {"invalid": "The email or password was not recognised.", "google": "Google sign-in was unavailable or not authorised."}
    return auth_page("login", messages.get(error, error), notice)


@rt("/login", methods=["POST"])
async def login_submit(request):
    data = await request.form()
    user = IdentityService().authenticate(str(data.get("email", "")), str(data.get("password", "")))
    if not user:
        return RedirectResponse("/login?error=invalid", status_code=303)
    identity = IdentityService()
    pending_invitation = str(request.session.get("pending_invitation", ""))
    if pending_invitation:
        try:
            user, organisation = identity.accept_invitation(pending_invitation, user_id=user["id"])
            _login(request.session, user, organisation)
            return RedirectResponse("/app?notice=Invitation+accepted", status_code=303)
        except Exception as exc:
            return RedirectResponse(f"/login?error={quote(str(exc))}", status_code=303)
    memberships = identity.memberships(user["id"])
    if not memberships:
        return RedirectResponse("/login?error=No+active+workspace", status_code=303)
    organisation = identity.organisation(memberships[0]["organisation_id"])
    _login(request.session, user, organisation)
    return RedirectResponse("/app", status_code=303)


@rt("/signup", methods=["GET"])
def signup_form(error: str = ""):
    return auth_page("signup", error)


@rt("/signup", methods=["POST"])
async def signup_submit(request):
    data = await request.form()
    try:
        user, organisation = IdentityService().create_workspace(
            str(data.get("email", "")), str(data.get("password", "")),
            str(data.get("name", "")), str(data.get("organisation", "")),
        )
    except Exception as exc:
        return auth_page("signup", str(exc))
    if settings.require_email_verification:
        verification = IdentityService().issue_token(user["id"], "verify", 24 * 3600)
        if not send_account_action(user["email"], user["name"], "Verify your FastCLM account", f"/verify/{verification}"):
            return auth_page("login", "Verification email could not be sent. Contact the workspace administrator.")
        return auth_page("login", notice="Check your email to verify your account before signing in.")
    _login(request.session, user, organisation)
    return RedirectResponse("/app", status_code=303)


@rt("/verify/{verification_token}")
def verify_account(request, verification_token: str):
    user = IdentityService().consume_verification(verification_token)
    if not user:
        return RedirectResponse("/login?error=Verification+link+is+invalid+or+expired", status_code=303)
    memberships = IdentityService().memberships(user["id"])
    organisation = IdentityService().organisation(memberships[0]["organisation_id"])
    _login(request.session, user, organisation)
    return RedirectResponse("/app", status_code=303)


@rt("/forgot", methods=["GET"])
def forgot_form():
    return recovery_page("forgot")


@rt("/forgot", methods=["POST"])
async def forgot_submit(request):
    data = await request.form()
    requested = IdentityService().request_reset(str(data.get("email", "")))
    if requested:
        user, reset_token = requested
        send_account_action(user["email"], user["name"], "Reset your FastCLM password", f"/reset/{reset_token}")
    return recovery_page("forgot", notice="If an account exists, a reset link has been sent.")


@rt("/reset/{reset_token}", methods=["GET"])
def reset_form(reset_token: str):
    return recovery_page("reset", reset_token)


@rt("/reset", methods=["POST"])
async def reset_submit(request):
    data = await request.form()
    try:
        success = IdentityService().reset_password(str(data.get("token", "")), str(data.get("password", "")))
    except ValueError as exc:
        return recovery_page("reset", str(data.get("token", "")), str(exc))
    if not success:
        return recovery_page("reset", str(data.get("token", "")), "Reset link is invalid or expired.")
    return RedirectResponse("/login?notice=Password+updated.+You+can+sign+in+now", status_code=303)


@rt("/auth/google")
def google_start(request):
    if not google_enabled():
        return RedirectResponse("/login?error=Google+sign-in+is+not+configured", status_code=303)
    return RedirectResponse(google_authorize_url(request.session), status_code=303)


@rt("/auth/google/callback")
def google_callback(request, code: str = "", state: str = ""):
    try:
        profile = google_exchange(code, state, request.session)
        identity = IdentityService()
        pending_invitation = str(request.session.get("pending_invitation", ""))
        if pending_invitation:
            user = identity.ensure_oauth_user(profile["email"], profile["name"])
            user, organisation = identity.accept_invitation(pending_invitation, user_id=user["id"])
        else:
            user, organisation = identity.ensure_oauth_workspace(profile["email"], profile["name"])
        _login(request.session, user, organisation)
        return RedirectResponse("/app", status_code=303)
    except Exception:
        return RedirectResponse("/login?error=google", status_code=303)


@rt("/auth/test")
def test_auth(request):
    if not settings.allow_test_auth:
        return PlainTextResponse("Not found", status_code=404)
    user, organisation = ensure_demo()
    _login(request.session, user, organisation)
    return RedirectResponse("/app", status_code=303)


@rt("/logout")
def logout(request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@rt("/invitations/{invitation_token}")
def invitation_view(request, invitation_token: str, error: str = ""):
    invitation = IdentityService().invitation(invitation_token)
    request.session.setdefault("csrf_token", token())
    if invitation:
        request.session["pending_invitation"] = invitation_token
    actor = _actor(request)
    return invitation_page(invitation, invitation_token, request.session["csrf_token"], actor.email if actor else "", error)


@rt("/invitations/actions/accept", methods=["POST"])
async def invitation_accept(request):
    data = await request.form()
    invitation_token = str(data.get("token", ""))
    if not csrf_valid(request.session, str(data.get("csrf", ""))):
        return PlainTextResponse("Invalid CSRF token", status_code=403)
    actor = _actor(request)
    try:
        user, organisation = IdentityService().accept_invitation(
            invitation_token,
            user_id=actor.user_id if actor else "",
            name=str(data.get("name", "")),
            password=str(data.get("password", "")),
        )
        _login(request.session, user, organisation)
        return RedirectResponse("/app?notice=Invitation+accepted", status_code=303)
    except Exception as exc:
        invitation = IdentityService().invitation(invitation_token)
        return invitation_page(invitation, invitation_token, request.session["csrf_token"], actor.email if actor else "", str(exc))


@rt("/organisations/switch", methods=["POST"])
async def organisation_switch(request):
    actor, data = await _form(request)
    if isinstance(actor, Response):
        return actor
    organisation_id = str(data.get("organisation_id", ""))
    try:
        target_actor = IdentityService().actor(actor.user_id, organisation_id)
        organisation = IdentityService().organisation(organisation_id)
    except LookupError:
        return PlainTextResponse("Workspace not found", status_code=404)
    AuditService().record(target_actor, "session", actor.user_id, "session.organisation.switched", {"from": actor.organisation_id})
    _login(request.session, IdentityService().user(actor.user_id), organisation)
    return RedirectResponse("/app", status_code=303)


@rt("/app")
def workspace(request, thread: str = "", notice: str = ""):
    actor = _required(request, "assistant.use")
    if isinstance(actor, Response):
        return actor
    return assistant_page(actor, AssistantService().cockpit(actor, thread), usage(actor.user_id), request.session["csrf_token"], notice)


@rt("/overview")
def overview(request):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return dashboard_page(actor, ContractService().dashboard(actor))


@rt("/assistant/ask", methods=["POST"])
async def assistant_ask(request):
    actor, data = await _form(request, "assistant.use")
    if isinstance(actor, Response):
        return actor
    try:
        AssistantService().ask(
            actor,
            str(data.get("thread_id", "")),
            str(data.get("question", "")),
            str(data.get("skill_id", "")),
            str(data.get("contract_id", "")),
        )
        return RedirectResponse("/app", status_code=303)
    except Exception as exc:
        cockpit = AssistantService().cockpit(actor, str(data.get("thread_id", "")))
        return assistant_page(actor, cockpit, usage(actor.user_id), request.session["csrf_token"], str(exc))


@rt("/assistant/stream", methods=["POST"])
async def assistant_stream(request):
    actor, data = await _form(request, "assistant.use")
    if isinstance(actor, Response):
        return actor

    def events():
        try:
            for event in AssistantService().stream(
                actor,
                str(data.get("thread_id", "")),
                str(data.get("question", "")),
                str(data.get("skill_id", "")),
                str(data.get("contract_id", "")),
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@rt("/assistant/actions/{action_id}", methods=["POST"])
async def assistant_action(request, action_id: str):
    actor, data = await _form(request, "assistant.use")
    if isinstance(actor, Response):
        return actor
    try:
        result = AssistantService().decide(actor, action_id, str(data.get("decision", "")) == "confirm")
        return RedirectResponse(f"/app?thread={result['thread']['id']}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/app?notice={quote(str(exc))}", status_code=303)


@rt("/contracts")
def contracts(request, q: str = "", status: str = ""):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return contracts_page(actor, ContractService().list(actor, q, status), q, status)


@rt("/contracts/new", methods=["GET"])
def contract_new(request):
    actor = _required(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    return contract_new_page(actor, ContractService().counterparties(actor))


@rt("/contracts/new", methods=["POST"])
async def contract_create(request):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        item = ContractService().create(actor, dict(data))
        return RedirectResponse(f"/contracts/{item['id']}", status_code=303)
    except Exception as exc:
        return contract_new_page(actor, ContractService().counterparties(actor), str(exc))


@rt("/contracts/{contract_id}")
def contract_detail(request, contract_id: str, notice: str = ""):
    return _contract_page(request, contract_id, notice)


@rt("/contracts/{contract_id}/transition", methods=["POST"])
async def contract_transition(request, contract_id: str):
    actor, data = await _form(request, "contracts.transition")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().transition(actor, contract_id, str(data.get("target", "")))
        message = "Lifecycle updated"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/details", methods=["POST"])
async def contract_update(request, contract_id: str):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().update(actor, contract_id, dict(data))
        message = "Contract details updated"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/blocks", methods=["POST"])
async def block_add(request, contract_id: str):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().add_block(actor, contract_id, str(data.get("block_type", "paragraph")), str(data.get("content", "")))
        message = "Block added"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/blocks/{block_id}", methods=["POST"])
async def block_update(request, contract_id: str, block_id: str):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().update_block(actor, contract_id, block_id, str(data.get("block_type", "paragraph")), str(data.get("content", "")))
        message = "Draft updated"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/versions", methods=["POST"])
async def version_create(request, contract_id: str):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().snapshot(actor, contract_id, str(data.get("label", "Saved version")))
        message = "Immutable version saved"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/upload", methods=["POST"])
async def contract_upload(request, contract_id: str):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        upload = data.get("document")
        content = await upload.read()
        DocumentService().ingest(actor, contract_id, upload.filename, content)
        message = "Document imported as a new version"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/versions/{version_id}/download")
def version_download(request, version_id: str):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    version = get_database().one("SELECT * FROM contract_versions WHERE id=? AND organisation_id=?", (version_id, actor.organisation_id))
    if not version or not version["storage_path"]:
        return PlainTextResponse("Attachment not found", status_code=404)
    path = (settings.upload_dir / version["storage_path"]).resolve()
    root = settings.upload_dir.resolve()
    if root not in path.parents or not path.is_file():
        return PlainTextResponse("Attachment not found", status_code=404)
    if version["source_checksum"] and file_checksum(path) != version["source_checksum"]:
        return PlainTextResponse("Attachment integrity check failed", status_code=409)
    return FileResponse(path, media_type=version["media_type"], filename=version["source_filename"])


@rt("/versions/{version_id}/inline")
def version_inline(request, version_id: str):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    version = get_database().one("SELECT * FROM contract_versions WHERE id=? AND organisation_id=?", (version_id, actor.organisation_id))
    if not version or not version["storage_path"] or version["media_type"] != "application/pdf":
        return PlainTextResponse("PDF attachment not found", status_code=404)
    path = (settings.upload_dir / version["storage_path"]).resolve()
    root = settings.upload_dir.resolve()
    if root not in path.parents or not path.is_file():
        return PlainTextResponse("PDF attachment not found", status_code=404)
    if version["source_checksum"] and file_checksum(path) != version["source_checksum"]:
        return PlainTextResponse("Attachment integrity check failed", status_code=409)
    filename = str(version["source_filename"]).replace('"', "")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@rt("/pdf-provenance", methods=["POST"])
async def pdf_provenance(request):
    """Recheck a viewer quote against the tenant-scoped immutable version text."""
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    data = await request.json()
    match = re.fullmatch(r"/versions/([0-9a-f-]{36})/inline", str(data.get("source", "")))
    evidence = str(data.get("evidence", "")).strip()[:4000]
    if not match or not evidence:
        return JSONResponse({"ok": False, "verified": False})
    version = get_database().one(
        "SELECT id,body_text FROM contract_versions WHERE id=? AND organisation_id=? AND media_type='application/pdf'",
        (match.group(1), actor.organisation_id),
    )
    if not version:
        return PlainTextResponse("PDF attachment not found", status_code=404)
    start_word, end_word, word_count = find_word_range(evidence, version["body_text"])
    verified = start_word >= 0
    return JSONResponse({
        "ok": verified,
        "verified": verified,
        "start_word": start_word,
        "end_word": end_word,
        "word_count": word_count,
    })


@rt("/contracts/{contract_id}/obligations", methods=["POST"])
async def obligation_add(request, contract_id: str):
    actor, data = await _form(request, "obligations.manage")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().add_obligation(actor, contract_id, dict(data))
        message = "Obligation added"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/approval", methods=["POST"])
async def approval_create(request, contract_id: str):
    actor, data = await _form(request, "contracts.approve")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().approve(actor, contract_id, str(data.get("decision", "")), str(data.get("comment", "")))
        message = "Approval decision recorded"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/review", methods=["POST"])
async def review_create(request, contract_id: str):
    actor, data = await _form(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    try:
        result = ReviewService().review(actor, contract_id, use_ai=str(data.get("use_ai", "false")).lower() == "true")
        message = f"Review complete · {result['risk_level']} risk · {len(result['findings'])} findings"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/contracts/{contract_id}/signatures", methods=["POST"])
async def signature_prepare(request, contract_id: str):
    actor, data = await _form(request, "contracts.transition")
    if isinstance(actor, Response):
        return actor
    try:
        SignatureService().prepare(actor, contract_id, str(data.get("provider", "")), str(data.get("recipient_name", "")), str(data.get("recipient_email", "")))
        message = "Signature request payload prepared for review"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/contracts/{contract_id}?notice={quote(message)}", status_code=303)


@rt("/obligations")
def obligations(request, status: str = "open"):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return obligations_page(actor, ContractService().obligations(actor, status), status, request.session["csrf_token"])


@rt("/obligations/{obligation_id}/complete", methods=["POST"])
async def obligation_complete(request, obligation_id: str):
    actor, _ = await _form(request, "obligations.manage")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().complete_obligation(actor, obligation_id)
    except (LookupError, PermissionError) as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return RedirectResponse("/obligations", status_code=303)


@rt("/counterparties", methods=["GET"])
def counterparties(request):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return counterparties_page(actor, ContractService().counterparties(actor), request.session["csrf_token"])


@rt("/counterparties", methods=["POST"])
async def counterparty_create(request):
    actor, data = await _form(request, "contracts.edit")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().add_counterparty(actor, dict(data))
        return RedirectResponse("/counterparties", status_code=303)
    except Exception as exc:
        return counterparties_page(actor, ContractService().counterparties(actor), request.session["csrf_token"], str(exc))


@rt("/clauses", methods=["GET"])
def clauses(request):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return clauses_page(actor, ContractService().clauses(actor), request.session["csrf_token"])


@rt("/clauses", methods=["POST"])
async def clause_create(request):
    actor, data = await _form(request, "clauses.manage")
    if isinstance(actor, Response):
        return actor
    try:
        ContractService().add_clause(actor, dict(data))
        return RedirectResponse("/clauses", status_code=303)
    except Exception as exc:
        return clauses_page(actor, ContractService().clauses(actor), request.session["csrf_token"], str(exc))


@rt("/skills", methods=["GET"])
def skills(request):
    actor = _required(request, "assistant.use")
    if isinstance(actor, Response):
        return actor
    return skills_page(actor, SkillService().list(actor), request.session["csrf_token"])


@rt("/skills", methods=["POST"])
async def skill_create(request):
    actor, data = await _form(request, "skills.manage")
    if isinstance(actor, Response):
        return actor
    try:
        skill = SkillService().create(actor, dict(data))
        return RedirectResponse(f"/skills/{skill['id']}", status_code=303)
    except Exception as exc:
        return skills_page(actor, SkillService().list(actor), request.session["csrf_token"], str(exc))


@rt("/skills/{skill_id}", methods=["GET"])
def skill_detail(request, skill_id: str):
    actor = _required(request, "assistant.use")
    if isinstance(actor, Response):
        return actor
    try:
        return skill_detail_page(actor, SkillService().get(actor, skill_id), request.session["csrf_token"])
    except LookupError:
        return PlainTextResponse("Skill not found", status_code=404)


@rt("/skills/{skill_id}", methods=["POST"])
async def skill_update(request, skill_id: str):
    actor, data = await _form(request, "skills.manage")
    if isinstance(actor, Response):
        return actor
    try:
        skill = SkillService().update(actor, skill_id, dict(data))
        return RedirectResponse(f"/skills/{skill['id']}", status_code=303)
    except Exception as exc:
        try:
            skill = SkillService().get(actor, skill_id)
        except LookupError:
            return PlainTextResponse("Skill not found", status_code=404)
        return skill_detail_page(actor, skill, request.session["csrf_token"], str(exc))


@rt("/audit")
def audit(request):
    actor = _required(request, "audit.view")
    if isinstance(actor, Response):
        return actor
    return audit_page(actor, AuditService().list(actor))


@rt("/team")
def team(request, notice: str = "", error: str = ""):
    actor = _required(request)
    if isinstance(actor, Response):
        return actor
    return team_page(actor, IdentityService().team(actor), request.session["csrf_token"], notice, error)


@rt("/team/invitations", methods=["POST"])
async def team_invite(request):
    actor, data = await _form(request, "team.manage")
    if isinstance(actor, Response):
        return actor
    try:
        invitation, invitation_token = IdentityService().invite(actor, str(data.get("email", "")), str(data.get("role", "")))
        delivered = send_account_action(
            invitation["email"], "there", f"Join {actor.organisation_name} on FastCLM", f"/invitations/{invitation_token}",
        )
        notice = "Invitation sent" if delivered else "Invitation created, but email delivery is not configured"
        return RedirectResponse(f"/team?notice={quote(notice)}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)


@rt("/team/invitations/{invitation_id}/revoke", methods=["POST"])
async def team_invitation_revoke(request, invitation_id: str):
    actor, _ = await _form(request, "team.manage")
    if isinstance(actor, Response):
        return actor
    try:
        IdentityService().revoke_invitation(actor, invitation_id)
        return RedirectResponse("/team?notice=Invitation+revoked", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)


@rt("/team/{user_id}/role", methods=["POST"])
async def team_role(request, user_id: str):
    actor, data = await _form(request, "team.manage")
    if isinstance(actor, Response):
        return actor
    try:
        IdentityService().update_role(actor, user_id, str(data.get("role", "")))
        return RedirectResponse("/team?notice=Role+updated", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)


@rt("/team/{user_id}/remove", methods=["POST"])
async def team_remove(request, user_id: str):
    actor, _ = await _form(request, "team.manage")
    if isinstance(actor, Response):
        return actor
    try:
        IdentityService().remove_member(actor, user_id)
        return RedirectResponse("/team?notice=Member+removed", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)


@rt("/settings")
def user_settings(request, notice: str = ""):
    actor = _required(request)
    if isinstance(actor, Response):
        return actor
    return settings_page(actor, key_status(actor.user_id), usage(actor.user_id), IdentityService().memberships(actor.user_id), request.session["csrf_token"], notice)


@rt("/settings/xai", methods=["POST"])
async def xai_key_save(request):
    actor, data = await _form(request)
    if isinstance(actor, Response):
        return actor
    try:
        store_xai_key(actor.user_id, str(data.get("api_key", "")))
        message = "xAI key encrypted and saved"
    except Exception as exc:
        message = str(exc)
    return RedirectResponse(f"/settings?notice={quote(message)}", status_code=303)


@rt("/settings/xai/remove", methods=["POST"])
async def xai_key_remove(request):
    actor, _ = await _form(request)
    if isinstance(actor, Response):
        return actor
    clear_xai_key(actor.user_id)
    return RedirectResponse("/settings?notice=Saved+xAI+key+removed", status_code=303)


@rt("/developers")
def developers():
    return developer_page()


@rt("/scim/v2/ServiceProviderConfig")
def scim_service_provider_config():
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": f"{settings.public_url}/developers",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken", "name": "Bearer token",
            "description": "FASTCLM_SCIM_TOKEN plus X-FastCLM-Organisation",
            "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
            "primary": True,
        }],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{settings.public_url}/scim/v2/ServiceProviderConfig"},
    })


@rt("/scim/v2/ResourceTypes")
def scim_resource_types():
    resource = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "User", "name": "User", "description": "FastCLM workspace member",
        "endpoint": "/Users", "schema": USER_SCHEMA,
        "meta": {"resourceType": "ResourceType", "location": f"{settings.public_url}/scim/v2/ResourceTypes/User"},
    }
    return _scim_response({"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": 1, "Resources": [resource]})


@rt("/scim/v2/Schemas")
def scim_schemas():
    schema = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
        "id": USER_SCHEMA, "name": "User", "description": "FastCLM workspace member",
        "attributes": [
            {"name": "userName", "type": "string", "multiValued": False, "required": True, "caseExact": False, "mutability": "immutable", "returned": "always", "uniqueness": "server"},
            {"name": "displayName", "type": "string", "multiValued": False, "required": False, "caseExact": False, "mutability": "readWrite", "returned": "default", "uniqueness": "none"},
            {"name": "externalId", "type": "string", "multiValued": False, "required": False, "caseExact": True, "mutability": "readWrite", "returned": "default", "uniqueness": "none"},
            {"name": "active", "type": "boolean", "multiValued": False, "required": False, "mutability": "readWrite", "returned": "default"},
        ],
        "meta": {"resourceType": "Schema", "location": f"{settings.public_url}/scim/v2/Schemas/{USER_SCHEMA}"},
    }
    return _scim_response({"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": 1, "Resources": [schema]})


@rt("/scim/v2/Users", methods=["GET"])
def scim_users(request, filter: str = "", startIndex: int = 1, count: int = 100):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        return _scim_response(SCIMService().list(organisation_id, filter, startIndex, count))
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/scim/v2/Users", methods=["POST"])
async def scim_user_create(request):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        resource = SCIMService().create(organisation_id, await request.json())
        return _scim_response(resource, 201, {"Location": resource["meta"]["location"]})
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/scim/v2/Users/{scim_id}", methods=["GET"])
def scim_user_get(request, scim_id: str):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        return _scim_response(SCIMService().get(organisation_id, scim_id))
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/scim/v2/Users/{scim_id}", methods=["PUT"])
async def scim_user_replace(request, scim_id: str):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        return _scim_response(SCIMService().replace(organisation_id, scim_id, await request.json()))
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/scim/v2/Users/{scim_id}", methods=["PATCH"])
async def scim_user_patch(request, scim_id: str):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        return _scim_response(SCIMService().patch(organisation_id, scim_id, await request.json()))
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/scim/v2/Users/{scim_id}", methods=["DELETE"])
def scim_user_delete(request, scim_id: str):
    organisation_id, error = _scim_organisation(request)
    if error:
        return error
    try:
        SCIMService().delete(organisation_id, scim_id)
        return PlainTextResponse("", status_code=204, media_type="application/scim+json")
    except SCIMError as exc:
        return _scim_error(exc)


@rt("/swagger.json")
def swagger_schema():
    return JSONResponse(api.openapi())


@rt("/healthz")
def healthz():
    try:
        migrations = int(get_database().scalar("SELECT COUNT(*) FROM schema_migrations") or 0)
        database_status = "ok"
    except Exception:
        migrations, database_status = 0, "error"
    return JSONResponse({
        "status": "ok" if database_status == "ok" else "degraded",
        "product": "FastCLM",
        "version": __version__,
        "environment": settings.environment,
        "database": {"status": database_status, "dialect": "sqlite", "migrations": migrations},
        "ai": {"provider": "xai", "model": settings.xai_model, "platform_key": "configured" if settings.xai_api_key else "disabled"},
        "email": "configured" if settings.postmark_api_token else "disabled",
        "scim": "configured" if settings.scim_token else "disabled",
        "reminders": {"scheduler": "enabled" if settings.reminder_scheduler_enabled else "disabled"},
    }, status_code=200 if database_status == "ok" else 503)


register_seo_routes(app)
for route_index, route in enumerate(app.routes):
    if getattr(route, "path", "") == "/favicon.ico":
        app.routes.insert(0, app.routes.pop(route_index))
        break


serve(host="0.0.0.0", port=settings.port, reload=False)
