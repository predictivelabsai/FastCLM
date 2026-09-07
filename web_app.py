"""FastCLM FastHTML entry point and browser routes."""
from __future__ import annotations

from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import *
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from fastclm import __version__
from fastclm.api import api
from fastclm.auth import google_authorize_url, google_enabled, google_exchange
from fastclm.bootstrap import ensure_demo, initialize
from fastclm.config import settings
from fastclm.database import get_database
from fastclm.emailer import send_account_action
from fastclm.security import Actor, csrf_valid, token
from fastclm.services.audit import AuditService
from fastclm.services.contracts import ContractService
from fastclm.services.credentials import clear_xai_key, key_status, store_xai_key, usage
from fastclm.services.documents import DocumentService
from fastclm.services.identity import IdentityService
from fastclm.services.review import ReviewService
from fastclm.services.signatures import SignatureService
from fastclm.web.ui import (
    audit_page,
    auth_page,
    clauses_page,
    contract_detail_page,
    contract_new_page,
    contracts_page,
    counterparties_page,
    dashboard_page,
    developer_page,
    landing_page,
    obligations_page,
    settings_page,
    recovery_page,
)


app, rt = fast_app(
    live=False,
    pico=False,
    secret_key=settings.secret,
    max_age=8 * 60 * 60,
    same_site="lax",
    sess_https_only=settings.public_url.startswith("https://"),
)
app.mount("/static", StaticFiles(directory=settings.root / "static"), name="static")
app.mount("/api/v1", api)


@app.on_event("startup")
async def startup() -> None:
    initialize()


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
    try:
        contract = ContractService().get(actor, contract_id)
    except LookupError:
        return PlainTextResponse("Contract not found", status_code=404)
    return contract_detail_page(actor, contract, request.session["csrf_token"], usage(actor.user_id), notice)


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
    memberships = IdentityService().memberships(user["id"])
    if not memberships:
        return RedirectResponse("/login?error=No+active+workspace", status_code=303)
    organisation = IdentityService().organisation(memberships[0]["organisation_id"])
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
        user, organisation = IdentityService().ensure_oauth_workspace(profile["email"], profile["name"])
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


@rt("/app")
def workspace(request):
    actor = _required(request, "contracts.view")
    if isinstance(actor, Response):
        return actor
    return dashboard_page(actor, ContractService().dashboard(actor))


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
    return FileResponse(path, media_type=version["media_type"], filename=version["source_filename"])


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


@rt("/audit")
def audit(request):
    actor = _required(request, "audit.view")
    if isinstance(actor, Response):
        return actor
    return audit_page(actor, AuditService().list(actor))


@rt("/settings")
def user_settings(request, notice: str = ""):
    actor = _required(request)
    if isinstance(actor, Response):
        return actor
    return settings_page(actor, key_status(actor.user_id), usage(actor.user_id), request.session["csrf_token"], notice)


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
    }, status_code=200 if database_status == "ok" else 503)


def robots(_request):
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /app\nDisallow: /contracts\nDisallow: /obligations\nDisallow: /counterparties\nDisallow: /clauses\nDisallow: /audit\nDisallow: /settings\nSitemap: {settings.public_url}/sitemap.xml\n")


def sitemap(_request):
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + f"<url><loc>{settings.public_url}/</loc></url><url><loc>{settings.public_url}/developers</loc></url></urlset>"
    return Response(body, media_type="application/xml")


app.router.routes.insert(0, Route("/sitemap.xml", sitemap, methods=["GET"]))
app.router.routes.insert(0, Route("/robots.txt", robots, methods=["GET"]))


serve(host="0.0.0.0", port=settings.port, reload=False)
