"""Public developer documentation for FastCLM."""
from fasthtml.common import *

from fastclm.config import settings
from fastclm.web.ui import logo

from .seo import seo_meta


def developer_page() -> Html:
    resources = (
        ("Contracts", "Search lifecycle records and retrieve version and obligation metadata.", "/api/v1/contracts", "GET"),
        ("Obligations", "Read due work or create an audited obligation for a workspace contract.", "/api/v1/obligations", "GET · POST"),
        ("Counterparties", "Connect contract relationships to finance, CRM, and reporting systems.", "/api/v1/counterparties", "GET"),
        ("Electronic signatures", "Prepare provider-neutral DocuSign and SignWell payloads in the workspace UI.", "/contracts/{id}/signatures", "POST"),
    )
    description = "Private FastCLM API, OpenAPI schemas, and electronic-signature adapter contracts."
    return Html(
        Head(
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1, viewport-fit=cover"),
            Meta(name="description", content=description),
            Meta(name="theme-color", content="#2457d6"),
            Title("Developer platform · FastCLM"),
            *seo_meta(path="/developers", title="FastCLM Developer API · FastSME", description=description),
            Link(rel="icon", href="/static/favicon.svg", type="image/svg+xml"),
            Link(rel="stylesheet", href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,600&display=swap"),
            Link(rel="stylesheet", href="/static/app.css?v=2"),
        ),
        Body(
            Header(logo(), Nav(A("API docs", href="/api/docs", cls="public-link"), A("Sign In", href="/login", cls="public-signin"), cls="public-links"), cls="public-nav"),
            Main(
                Div(
                    P("DEVELOPER PLATFORM · API V1", cls="eyebrow"),
                    H1("Build on FastCLM without making contracts public."),
                    P("The integration API is private, versioned, and organisation-scoped. Configure a server-side bearer token, then send the workspace ID explicitly on every data request.", cls="dev-lede"),
                    Div(
                        A("Open Swagger UI", href="/api/docs", cls="button"),
                        A("Open ReDoc", href="/api/redoc", cls="button secondary"),
                        A("Download OpenAPI", href="/api/openapi.json", cls="button secondary"),
                        A("Download swagger.json", href="/swagger.json", cls="button secondary"),
                        A("View source", href="https://github.com/predictivelabsai/FastCLM", cls="button secondary"),
                        cls="hero-actions",
                    ),
                    Div(Strong("Private by default. "), "All data endpoints return 503 until FASTCLM_API_TOKEN (or its fleet-standard FASTSME_API_TOKEN alias) is configured. They then require Authorization: Bearer <token> and X-FastCLM-Organisation: <workspace-id>.", cls="callout"),
                    Div(*[
                        Article(H2(title), P(copy), Code(Span(method, cls="method"), f" {route}", cls="route"), cls="dev-card")
                        for title, copy, route, method in resources
                    ], cls="dev-grid"),
                    H2("API contract"),
                    Div(
                        P(Strong("Base URL: "), Code(f"{settings.public_url}/api")),
                        P(Strong("Pagination: "), Code("?limit=20&offset=0")),
                        P(Strong("Errors: "), Code('{"error":{"code":"…","message":"…","details":{}}}')),
                        P(Strong("Writes: "), "POST operations additionally require X-FastCLM-Actor with an authorised workspace member ID for permission checks and audit attribution."),
                        cls="panel form-stack",
                    ),
                    H2("Quick start"),
                    Pre(Code(f'''curl "{settings.public_url}/api/v1/contracts?limit=20&offset=0" \\
  -H "Authorization: Bearer $FASTCLM_API_TOKEN" \\
  -H "X-FastCLM-Organisation: $FASTCLM_ORGANISATION_ID"'''), cls="code"),
                    H2("Create an obligation"),
                    Pre(Code(f'''curl -X POST "{settings.public_url}/api/v1/obligations" \\
  -H "Authorization: Bearer $FASTCLM_API_TOKEN" \\
  -H "X-FastCLM-Organisation: $FASTCLM_ORGANISATION_ID" \\
  -H "X-FastCLM-Actor: $FASTCLM_USER_ID" \\
  -H "Content-Type: application/json" \\
  -d '{{"contract_id":"…","title":"Send renewal notice","due_date":"2026-11-01"}}' '''), cls="code"),
                    H2("Signature providers"),
                    P("The current adapters create reviewable local payloads only. SignWell maps to POST /api/v1/documents with X-Api-Key authentication, draft/test-mode controls, recipients, metadata, and source-version context. DocuSign maps to an envelope draft. Dispatch and webhook processing remain deliberately gated follow-up work.", cls="dev-lede"),
                    P(A("SignWell create-document reference ↗", href="https://developers.signwell.com/reference/createdocument", target="_blank", rel="noopener noreferrer", cls="quiet-link")),
                    cls="dev-wrap",
                ),
            ),
            cls="public-body",
        ),
    )
