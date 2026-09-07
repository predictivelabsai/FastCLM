"""FastHTML components for the public site and authenticated workspace."""
from __future__ import annotations

import json
from datetime import date

from fasthtml.common import *

from fastclm.config import settings
from fastclm.lifecycle import STATUSES
from fastclm.security import Actor


def head(title: str, description: str = "Open-source contract lifecycle management for SMEs.", canonical_path: str = "") -> Head:
    canonical = f"{settings.public_url}{canonical_path}" if canonical_path else ""
    return Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1, viewport-fit=cover"),
        Meta(name="theme-color", content="#2457d6"),
        Meta(name="description", content=description),
        Meta(property="og:title", content=f"{title} · FastCLM"),
        Meta(property="og:description", content=description),
        Meta(property="og:type", content="website"),
        Meta(property="og:url", content=canonical) if canonical else None,
        Meta(name="twitter:card", content="summary"),
        Title(f"{title} · FastCLM"),
        Link(rel="canonical", href=canonical) if canonical else None,
        Link(rel="icon", href="/static/favicon.svg", type="image/svg+xml"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        Link(rel="stylesheet", href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,600&display=swap"),
        Link(rel="stylesheet", href="/static/app.css?v=1"),
    )


def logo() -> A:
    return A(Span("F", cls="brand-mark"), Span("Fast", cls="brand-fast"), Span("CLM", cls="brand-accent"), href="/", cls="brand")


def product_mock() -> Div:
    return Div(
        Div(Span(cls="mock-dot"), Span(cls="mock-dot"), Span(cls="mock-dot"), cls="mock-bar"),
        Div(
            Div(*[Span() for _ in range(6)], cls="mock-side"),
            Div(
                Div(cls="mock-title"),
                Div(Div(B("42"), Small("Contracts"), cls="mock-stat"), Div(B("6"), Small("In review"), cls="mock-stat"), Div(B("3"), Small("Renewals due"), cls="mock-stat"), cls="mock-stats"),
                Div(Div(Strong("Cloud services master agreement"), Small("Northstar Cloud · CLM-2026-001")), Span("Active", cls="mock-pill"), cls="mock-row"),
                Div(Div(Strong("EU data processing agreement"), Small("Atelier Europa · CLM-2026-002")), Span("Review", cls="mock-pill"), cls="mock-row"),
                Div(Div(Strong("Software licence renewal"), Small("Orchard Systems · CLM-2026-003")), Span("Approval", cls="mock-pill"), cls="mock-row"),
                cls="mock-main",
            ),
            cls="mock-layout",
        ),
        cls="mock-window",
    )


def landing_page() -> Html:
    description = "Upload, review, approve, sign, and manage contracts, obligations, and renewals in one open workspace."
    features = (
        ("One contract record", "Keep Word and PDF originals, editable blocks, counterparties, commercial facts, and immutable versions together."),
        ("Governed lifecycle", "Move from draft to review, approval, signature, and active management through explicit, audited gates."),
        ("Dates that do work", "Track obligations, notice windows, renewals, expiry, and accountable owners before deadlines become surprises."),
    )
    return Html(
        head("Open contract management", description, "/"),
        Body(
            Header(
                logo(),
                Nav(
                    A("Developers", href="/developers", cls="public-link"),
                    A("API", href="/api/v1/docs", cls="public-link"),
                    A("Sign In", href="/login", cls="public-signin"),
                    cls="public-links",
                ),
                cls="public-nav",
            ),
            Main(
                Section(
                    Div(
                        P("OPEN CONTRACT LIFECYCLE MANAGEMENT", cls="eyebrow"),
                        H1("Know what you agreed—and what happens next."),
                        P(description, cls="hero-copy"),
                        Div(A("Create your workspace", href="/signup", cls="button"), A("Explore the API", href="/developers", cls="button secondary"), cls="hero-actions"),
                        P("MIT licensed · SQLite included · Your documents stay private", cls="proof"),
                    ),
                    Div(product_mock(), cls="hero-product"),
                    cls="hero",
                ),
                Section(
                    Div(*[
                        Article(Span(f"0{index}", cls="num"), H2(title), P(copy), cls="feature-card")
                        for index, (title, copy) in enumerate(features, 1)
                    ], cls="feature-grid"),
                    cls="feature-band",
                ),
                Section(
                    Div(P("DEVELOPERS", cls="eyebrow"), H2("Integrate without opening your contracts."), P("Use the private, organisation-scoped API, generated OpenAPI schema, and electronic-signature adapter contracts. Data endpoints stay disabled until an API token is configured.")),
                    Div(A("Developer guide", href="/developers", cls="button"), A("Open API docs", href="/api/v1/docs", cls="button secondary"), cls="hero-actions"),
                    cls="public-section",
                ),
            ),
            Footer(Span("FastCLM is part of the open-source FastSME suite."), A("View all products", href="https://fastsme.com/products", cls="quiet-link"), cls="public-footer"),
            cls="public-body",
        ),
    )


def auth_page(mode: str = "login", error: str = "", notice: str = "") -> Html:
    signup = mode == "signup"
    return Html(
        head("Create workspace" if signup else "Sign in"),
        Body(
            Main(
                Div(
                    A("← Back to FastCLM", href="/", cls="back-link"),
                    Div(
                        logo(),
                        H1("Create your workspace" if signup else "Welcome back"),
                        P("Start an isolated contract workspace for your organisation." if signup else "Sign in to manage your agreements and obligations.", cls="muted"),
                        Div(notice, cls="alert success") if notice else None,
                        Div(error, cls="alert error") if error else None,
                        Form(
                            Label("Your name", Input(name="name", required=True, autocomplete="name")) if signup else None,
                            Label("Organisation", Input(name="organisation", required=True, autocomplete="organization")) if signup else None,
                            Label("Email", Input(type="email", name="email", required=True, autocomplete="email")),
                            Label("Password", Input(type="password", name="password", required=True, minlength="10", autocomplete="new-password" if signup else "current-password")),
                            Button("Create workspace" if signup else "Sign in", type="submit", cls="button full"),
                            action="/signup" if signup else "/login", method="post", cls="auth-form",
                        ),
                        Div("OR", cls="auth-divider"),
                        A("Continue with Google", href="/auth/google", cls="button secondary full"),
                        P(A("Forgot your password?", href="/forgot"), cls="auth-switch") if not signup else None,
                        P(A("Already have an account? Sign in", href="/login") if signup else A("New to FastCLM? Create a workspace", href="/signup"), cls="auth-switch"),
                        cls="auth-card",
                    ),
                    cls="auth-wrap",
                ),
                cls="auth-page",
            ),
        ),
    )


def recovery_page(mode: str, token_value: str = "", error: str = "", notice: str = "") -> Html:
    reset = mode == "reset"
    return Html(
        head("Reset password"),
        Body(Main(Div(A("← Back to sign in", href="/login", cls="back-link"), Div(
            logo(), H1("Choose a new password" if reset else "Reset your password"),
            P("Enter a new password of at least ten characters." if reset else "We will send a one-hour reset link if the account exists.", cls="muted"),
            Div(notice, cls="alert success") if notice else None,
            Div(error, cls="alert error") if error else None,
            Form(Input(type="hidden", name="token", value=token_value), Label("New password", Input(type="password", name="password", minlength="10", required=True)), Button("Reset password", cls="button full"), action="/reset", method="post", cls="form-stack") if reset else
            Form(Label("Email", Input(type="email", name="email", required=True)), Button("Send reset link", cls="button full"), action="/forgot", method="post", cls="form-stack"),
            cls="auth-card"), cls="auth-wrap"), cls="auth-page")),
    )


NAV = (
    ("Overview", "/app", "dashboard", "contracts.view"),
    ("Contracts", "/contracts", "contracts", "contracts.view"),
    ("Obligations", "/obligations", "obligations", "contracts.view"),
    ("Counterparties", "/counterparties", "counterparties", "contracts.view"),
    ("Clause library", "/clauses", "clauses", "contracts.view"),
    ("Audit trail", "/audit", "audit", "audit.view"),
    ("Settings", "/settings", "settings", None),
)


def sidebar(actor: Actor, active: str) -> Aside:
    return Aside(
        Div(logo(), Button("×", type="button", cls="drawer-close", onclick="toggleNav()"), cls="sidebar-head"),
        Nav(*[A(label, href=href, cls=f"nav-item {'active' if active == key else ''}") for label, href, key, permission in NAV if not permission or actor.can(permission)], cls="side-nav"),
        Div(
            Div(Span(actor.name[:1].upper(), cls="avatar"), Div(Strong(actor.name), Small(actor.organisation_name)), cls="identity"),
            A("Sign out", href="/logout", cls="signout"),
            cls="sidebar-foot",
        ),
        id="sidebar", cls="sidebar",
    )


def shell(actor: Actor, active: str, title: str, content) -> Html:
    return Html(
        head(title),
        Body(
            Div(cls="drawer-overlay", onclick="toggleNav()"),
            sidebar(actor, active),
            Main(
                Header(Button("☰", type="button", cls="mobile-nav", onclick="toggleNav()"), Div(H1(title), Small(actor.organisation_name)), Span(actor.email, cls="workspace-user"), cls="workspace-head"),
                content,
                cls="workspace-main",
            ),
            Script("function toggleNav(){document.body.classList.toggle('nav-open')}"),
            cls="app-shell",
        ),
    )


def status_badge(value: str):
    return Span(value.replace("_", " ").title(), cls=f"status {value.replace('_', '-')}")


def stat(label: str, value) -> Div:
    return Div(Strong(str(value)), Span(label), cls="stat-card")


def page_intro(eyebrow: str, title: str, copy: str, action=None) -> Div:
    return Div(Div(P(eyebrow, cls="eyebrow"), H2(title), P(copy, cls="muted")), action, cls="page-intro")


def empty_state(title: str, copy: str) -> Div:
    return Div(H3(title), P(copy), cls="empty")


def dashboard_page(actor: Actor, data: dict) -> Html:
    recent = [
        A(Div(H3(item["title"]), P(f"{item['reference']} · {item['counterparty_name'] or 'No counterparty'}", cls="muted")), Div(status_badge(item["status"]), status_badge(item["risk_level"]), cls="inline-actions"), href=f"/contracts/{item['id']}", cls="table-row")
        for item in data["recent"]
    ]
    upcoming = [
        A(Div(H3(item["title"]), P(f"{item['reference']} · {item['contract_title']}", cls="muted")), Div(Strong(item["due_date"] or "No date"), status_badge("overdue" if item["due_date"] and item["due_date"] < date.today().isoformat() else "due_soon"), cls="table-meta"), href=f"/contracts/{item['contract_id']}", cls="table-row")
        for item in data["upcoming"]
    ]
    content = Div(
        page_intro("CONTRACT OPERATIONS", "The agreements that need attention", "See lifecycle work, obligations, renewal windows, and recent records across your workspace.", A("New contract", href="/contracts/new", cls="button") if actor.can("contracts.edit") else None),
        Div(stat("All contracts", data["total"]), stat("Active", data["active"]), stat("In review", data["in_review"]), stat("Expiring in 90 days", data["expiring"]), stat("Overdue obligations", data["overdue"]), cls="stats-grid"),
        Div(Section(Div(H3("Recent contracts"), A("Open register →", href="/contracts", cls="quiet-link"), cls="subhead"), Div(*recent, cls="table-card") if recent else empty_state("No contracts yet", "Create the first contract record."), cls="panel"), Section(Div(H3("Upcoming obligations"), A("View all →", href="/obligations", cls="quiet-link"), cls="subhead"), Div(*upcoming, cls="table-card") if upcoming else empty_state("Nothing due", "Open obligations will appear here."), cls="panel"), cls="two-column"),
        cls="page-scroll",
    )
    return shell(actor, "dashboard", "Overview", content)


def contracts_page(actor: Actor, records: list[dict], q: str = "", selected_status: str = "") -> Html:
    cards = [
        A(
            Div(status_badge(item["status"]), Small(item["reference"]), cls="record-card-top"),
            H3(item["title"]), P(item["counterparty_name"] or "No counterparty"),
            Div(Span(f"{item['currency']} {item['value_amount']}" if item["value_amount"] else "Value not set"), status_badge(item["risk_level"]), cls="record-card-foot"),
            href=f"/contracts/{item['id']}", cls="record-card",
        ) for item in records
    ]
    content = Div(
        page_intro("CONTRACT REGISTER", "Every agreement in one searchable record", "Find contracts by title, reference, counterparty, or lifecycle state.", A("New contract", href="/contracts/new", cls="button") if actor.can("contracts.edit") else None),
        Form(Input(name="q", value=q, placeholder="Search contracts, references, or counterparties"), Select(Option("All statuses", value=""), *[Option(value.title(), value=value, selected=value == selected_status) for value in STATUSES], name="status"), Button("Filter", cls="button secondary"), method="get", action="/contracts", cls="filters"),
        Div(*cards, cls="record-grid") if cards else empty_state("No matching contracts", "Change the filters or create a contract."),
        cls="page-scroll",
    )
    return shell(actor, "contracts", "Contracts", content)


def contract_new_page(actor: Actor, counterparties: list[dict], error: str = "") -> Html:
    content = Div(
        page_intro("NEW CONTRACT", "Create a contract record", "Start with the commercial facts, then upload a Word or PDF version or draft in editable blocks."),
        Div(error, cls="alert error") if error else None,
        Form(
            Label("Title", Input(name="title", required=True, placeholder="Cloud services master agreement")),
            Div(Label("Reference", Input(name="reference", placeholder="Generated when blank")), Label("Contract type", Select(*[Option(value) for value in ("Commercial agreement", "Master services agreement", "Statement of work", "Non-disclosure agreement", "Data processing agreement", "Software licence", "Supplier agreement")], name="contract_type")), cls="form-row"),
            Div(Label("Counterparty", Select(Option("No counterparty", value=""), *[Option(item["name"], value=item["id"]) for item in counterparties], name="counterparty_id")), Label("Jurisdiction", Select(Option("England and Wales"), Option("Scotland"), Option("Northern Ireland"), Option("European Union"), Option("Ireland"), Option("Other"), name="jurisdiction")), cls="form-row"),
            Label("Summary", Textarea(name="summary", rows="3")),
            Div(Label("Value", Input(name="value_amount", inputmode="decimal")), Label("Currency", Select(*[Option(value) for value in ("GBP", "EUR", "USD")], name="currency")), cls="form-row"),
            Div(Label("Effective date", Input(type="date", name="effective_date")), Label("Expiry date", Input(type="date", name="expiry_date")), cls="form-row"),
            Div(Label("Notice deadline", Input(type="date", name="notice_date")), Label("Renewal", Select(Option("No renewal", value="none"), Option("Manual", value="manual"), Option("Automatic", value="automatic"), name="renewal_type")), cls="form-row"),
            Button("Create contract", cls="button"), action="/contracts/new", method="post", cls="panel form-stack",
        ),
        cls="page-scroll narrow",
    )
    return shell(actor, "contracts", "New contract", content)


def _editor(contract: dict, csrf: str, editable: bool):
    blocks = []
    for item in contract["blocks"]:
        if editable:
            blocks.append(Div(Form(Input(type="hidden", name="csrf", value=csrf), Select(*[Option(value.title(), value=value, selected=value == item["block_type"]) for value in ("heading", "paragraph", "list", "quote", "clause")], name="block_type"), Textarea(item["content"], name="content", rows="3"), Button("Save", cls="button small"), action=f"/contracts/{contract['id']}/blocks/{item['id']}", method="post"), cls=f"block {item['block_type']}"))
        else:
            blocks.append(Div(H3(item["content"]) if item["block_type"] == "heading" else P(item["content"]), cls=f"block {item['block_type']}"))
    return Div(*blocks)


def contract_detail_page(actor: Actor, contract: dict, csrf: str, usage: dict, notice: str = "") -> Html:
    editable = actor.can("contracts.edit") and contract["status"] in {"draft", "review"}
    allowed_transitions = [target for target in contract["next_statuses"] if not (contract["status"] == "approval" and target == "signature")]
    transitions = [Form(Input(type="hidden", name="csrf", value=csrf), Input(type="hidden", name="target", value=target), Button(f"Move to {target.title()}", cls="button small"), action=f"/contracts/{contract['id']}/transition", method="post") for target in allowed_transitions] if actor.can("contracts.transition") else []
    versions = [Div(Strong(f"Version {item['version_number']} · {item['label'] or 'Saved version'}"), Small(f"{item['source_filename'] or 'Edited in FastCLM'} · {item['created_at']}"), P(item["checksum"], cls="checksum"), cls="version-row") for item in contract["versions"]]
    obligations = [Div(Div(H3(item["title"]), P(item["description"], cls="muted")), Div(status_badge(item["status"]), Small(item["due_date"] or "No due date"), cls="table-meta"), cls="table-row") for item in contract["obligations"]]
    approvals = [Div(Div(H3(item["approver_name"]), P(item["comment"] or "No comment", cls="muted")), Div(status_badge(item["decision"]), Small(item["decided_at"]), cls="table-meta"), cls="table-row") for item in contract["approvals"]]
    signatures = [Div(Div(H3(f"{item['provider'].title()} · {item['recipient_name']}"), P(item["recipient_email"], cls="muted")), status_badge(item["status"]), cls="table-row") for item in contract["signatures"]]
    findings = []
    for review in contract["findings"]:
        for item in json.loads(review["findings_json"]):
            findings.append(Div(Div(H4(item.get("title", "Review point")), status_badge(item.get("severity", "medium")), cls="subhead"), P(item.get("guidance", "")), P(item.get("evidence", ""), cls="muted") if item.get("evidence") else None, cls="finding"))
    content = Div(
        Div(notice, cls="alert success") if notice else None,
        page_intro(contract["reference"], contract["title"], contract["summary"] or "No summary yet.", Div(status_badge(contract["status"]), status_badge(contract["risk_level"]), *transitions, cls="inline-actions")),
        Div(
            Div(Span("Counterparty"), Strong(contract["counterparty_name"] or "Not set"), cls="detail"),
            Div(Span("Type"), Strong(contract["contract_type"]), cls="detail"),
            Div(Span("Jurisdiction"), Strong(contract["jurisdiction"]), cls="detail"),
            Div(Span("Value"), Strong(f"{contract['currency']} {contract['value_amount']}" if contract["value_amount"] else "Not set"), cls="detail"),
            Div(Span("Effective"), Strong(contract["effective_date"] or "Not set"), cls="detail"),
            Div(Span("Expiry"), Strong(contract["expiry_date"] or "Not set"), cls="detail"),
            Div(Span("Notice"), Strong(contract["notice_date"] or "Not set"), cls="detail"),
            Div(Span("Renewal"), Strong(contract["renewal_type"].title()), cls="detail"),
            cls="detail-grid",
        ),
        Div(
            Div(
                Section(
                    Div(H3("Contract editor"), Span("Editable in draft and review", cls="muted") if editable else Span("Read only at this lifecycle stage", cls="muted"), cls="subhead"),
                    _editor(contract, csrf, editable),
                    Form(Input(type="hidden", name="csrf", value=csrf), Select(*[Option(value.title(), value=value) for value in ("heading", "paragraph", "list", "quote", "clause")], name="block_type"), Textarea(name="content", rows="3", placeholder="Add contract wording…", required=True), Button("Add block", cls="button small"), action=f"/contracts/{contract['id']}/blocks", method="post", cls="panel form-stack") if editable else None,
                    cls="panel",
                ),
                Section(
                    Div(H3("Versions"), Form(Input(type="hidden", name="csrf", value=csrf), Input(name="label", placeholder="Version label", required=True), Button("Save version", cls="button small"), action=f"/contracts/{contract['id']}/versions", method="post", cls="inline-actions") if editable else None, cls="subhead"),
                    *versions,
                    Form(Input(type="hidden", name="csrf", value=csrf), Label("Upload Word or PDF", Input(type="file", name="document", accept=".pdf,.docx,.txt,.md", required=True)), Button("Import as new version", cls="button"), enctype="multipart/form-data", action=f"/contracts/{contract['id']}/upload", method="post", cls="panel form-stack") if editable else None,
                    cls="panel",
                ),
                Section(Div(H3("Obligations"), cls="subhead"), Div(*obligations, cls="table-card") if obligations else empty_state("No obligations", "Add a deliverable, notice, payment, or compliance duty."), Form(Input(type="hidden", name="csrf", value=csrf), Label("Obligation", Input(name="title", required=True)), Label("Description", Textarea(name="description", rows="2")), Div(Label("Due date", Input(type="date", name="due_date")), Label("Recurrence", Select(*[Option(value.title(), value=value) for value in ("none", "monthly", "quarterly", "annual")], name="recurrence")), cls="form-row"), Button("Add obligation", cls="button small"), action=f"/contracts/{contract['id']}/obligations", method="post", cls="panel form-stack") if actor.can("obligations.manage") else None, cls="panel"),
                cls="section-stack",
            ),
            Div(
                Section(H3("Contract review"), P("Rule-based review is always available. xAI provides a deeper assistive review and never changes approval or lifecycle state.", cls="muted"), Div(Span(f"{usage['remaining']} of {usage['limit']} included reviews remain" if not usage["has_byok"] else "Using your encrypted xAI key", cls="callout")), Form(Input(type="hidden", name="csrf", value=csrf), Input(type="hidden", name="use_ai", value="false"), Button("Run local review", cls="button secondary full"), action=f"/contracts/{contract['id']}/review", method="post"), Form(Input(type="hidden", name="csrf", value=csrf), Input(type="hidden", name="use_ai", value="true"), Button("Review with xAI", cls="button full"), action=f"/contracts/{contract['id']}/review", method="post"), *findings, cls="panel form-stack"),
                Section(H3("Approval decisions"), Div(*approvals, cls="table-card") if approvals else P("No decisions recorded.", cls="muted"), Form(Input(type="hidden", name="csrf", value=csrf), Select(Option("Approve", value="approved"), Option("Request changes", value="changes_requested"), name="decision"), Textarea(name="comment", rows="2", placeholder="Decision rationale"), Button("Record decision", cls="button"), action=f"/contracts/{contract['id']}/approval", method="post", cls="form-stack") if actor.can("contracts.approve") and contract["status"] == "approval" else None, cls="panel"),
                Section(H3("Electronic signature"), P("Prepare a provider payload for review. No envelope or document is sent automatically.", cls="muted"), Div(*signatures, cls="table-card") if signatures else None, Form(Input(type="hidden", name="csrf", value=csrf), Select(Option("SignWell", value="signwell"), Option("DocuSign", value="docusign"), name="provider"), Input(name="recipient_name", placeholder="Signer name", required=True), Input(type="email", name="recipient_email", placeholder="signer@example.com", required=True), Button("Prepare signature request", cls="button"), action=f"/contracts/{contract['id']}/signatures", method="post", cls="form-stack") if actor.can("contracts.transition") and contract["status"] == "signature" else None, cls="panel"),
                cls="section-stack",
            ),
            cls="two-column",
        ),
        cls="page-scroll",
    )
    return shell(actor, "contracts", contract["title"], content)


def obligations_page(actor: Actor, rows: list[dict], selected_status: str = "open", csrf: str = "") -> Html:
    items = [Div(Div(H3(item["title"]), P(f"{item['reference']} · {item['contract_title']} · {item['owner_name'] or 'Unassigned'}", cls="muted")), Div(status_badge(item["status"]), Small(item["due_date"] or "No due date"), Form(Input(type="hidden", name="csrf", value=csrf), Button("Complete", cls="button small"), action=f"/obligations/{item['id']}/complete", method="post") if item["status"] == "open" and actor.can("obligations.manage") else None, cls="table-meta"), cls="table-row") for item in rows]
    content = Div(page_intro("OBLIGATIONS", "Turn contract promises into owned work", "Track delivery, notice, payment, reporting, and compliance duties by due date."), Div(*[A(value.title(), href=f"/obligations?status={value}", cls=f"tab {'active' if value == selected_status else ''}") for value in ("open", "complete", "waived")], cls="tabs"), Div(*items, cls="table-card") if items else empty_state("No obligations", "Obligations added to contracts will appear here."), cls="page-scroll")
    return shell(actor, "obligations", "Obligations", content)


def counterparties_page(actor: Actor, rows: list[dict], csrf: str, error: str = "") -> Html:
    items = [Div(Div(H3(item["name"]), P(f"{item['jurisdiction'] or 'Jurisdiction not set'} · {item['registration_number'] or 'No registration number'}", cls="muted")), Div(Strong(str(item["contract_count"])), Small("contracts"), cls="table-meta"), cls="table-row") for item in rows]
    form = Form(Input(type="hidden", name="csrf", value=csrf), Label("Legal name", Input(name="name", required=True)), Div(Label("Registration number", Input(name="registration_number")), Label("Jurisdiction", Input(name="jurisdiction")), cls="form-row"), Div(Label("Contact", Input(name="contact_name")), Label("Contact email", Input(type="email", name="contact_email")), cls="form-row"), Button("Add counterparty", cls="button"), action="/counterparties", method="post", cls="panel form-stack") if actor.can("contracts.edit") else None
    content = Div(page_intro("COUNTERPARTIES", "The organisations across your agreements", "Keep legal identity and contract relationships together."), Div(error, cls="alert error") if error else None, Div(Section(Div(*items, cls="table-card") if items else empty_state("No counterparties", "Add the first legal entity.")), Section(form) if form else None, cls="two-column"), cls="page-scroll")
    return shell(actor, "counterparties", "Counterparties", content)


def clauses_page(actor: Actor, rows: list[dict], csrf: str, error: str = "") -> Html:
    items = [Article(Div(P(item["category"], cls="eyebrow"), status_badge(item["jurisdiction"]), cls="subhead"), H3(item["title"]), P(item["body"]), P(Strong("Review guidance: "), item["risk_guidance"], cls="muted") if item["risk_guidance"] else None, cls="panel") for item in rows]
    form = Form(Input(type="hidden", name="csrf", value=csrf), Label("Title", Input(name="title", required=True)), Div(Label("Category", Input(name="category", value="General")), Label("Jurisdiction", Input(name="jurisdiction", value="UK / EU")), cls="form-row"), Label("Preferred wording", Textarea(name="body", rows="5", required=True)), Label("Fallback wording", Textarea(name="fallback_body", rows="3")), Label("Review guidance", Textarea(name="risk_guidance", rows="2")), Button("Add clause", cls="button"), action="/clauses", method="post", cls="panel form-stack") if actor.can("clauses.manage") else None
    content = Div(page_intro("CLAUSE LIBRARY", "Reusable UK and EU drafting knowledge", "Use preferred language, fallbacks, and review notes as a starting point—not jurisdiction-specific legal advice."), Div(error, cls="alert error") if error else None, Div(Div(*items, cls="section-stack"), form, cls="two-column"), cls="page-scroll")
    return shell(actor, "clauses", "Clause library", content)


def audit_page(actor: Actor, rows: list[dict]) -> Html:
    items = [Div(Div(H3(item["action"].replace(".", " ").title()), P(f"{item['entity_type']} · {item['entity_id']}", cls="muted")), Div(Strong(item["actor_name"] or "System"), Small(item["created_at"]), cls="table-meta"), cls="table-row") for item in rows]
    content = Div(page_intro("AUDIT TRAIL", "A durable record of contract activity", "Every material mutation and decision is written as an append-only event."), Div(*items, cls="table-card") if items else empty_state("No activity", "Workspace events will appear here."), cls="page-scroll")
    return shell(actor, "audit", "Audit trail", content)


def settings_page(actor: Actor, key: dict, usage: dict, csrf: str, notice: str = "") -> Html:
    content = Div(
        page_intro("SETTINGS", "AI review and workspace access", "FastCLM includes five platform-funded xAI reviews per user. Add your own key to continue without using that allowance."),
        Div(notice, cls="alert success") if notice else None,
        Div(
            Section(H3("AI usage"), Div(stat("Included used", f"{usage['used']} / {usage['limit']}"), stat("Remaining", usage["remaining"]), cls="form-row"), P("Your saved key is used before the platform key and does not consume the included allowance.", cls="muted"), cls="panel"),
            Section(H3("xAI API key (BYOK)"), P(f"Status: {key['hint']}" if key["configured"] else "No personal key configured", cls="callout"), Form(Input(type="hidden", name="csrf", value=csrf), Label("API key", Input(type="password", name="api_key", autocomplete="new-password", placeholder="xai-…", required=True)), Button("Save encrypted key", cls="button"), action="/settings/xai", method="post", cls="form-stack"), Form(Input(type="hidden", name="csrf", value=csrf), Button("Remove saved key", cls="button danger"), action="/settings/xai/remove", method="post") if key["configured"] else None, P("The key is encrypted at rest and is never returned to the browser.", cls="muted"), cls="panel"),
            cls="two-column",
        ),
        cls="page-scroll",
    )
    return shell(actor, "settings", "Settings", content)


def developer_page() -> Html:
    resources = (
        ("Contracts", "Search lifecycle records and retrieve version and obligation metadata.", "/api/v1/contracts"),
        ("Obligations", "Read due work across agreements for reporting or workflow automation.", "/api/v1/obligations"),
        ("Counterparties", "Connect contract relationships to finance, CRM, and vendor systems.", "/api/v1/counterparties"),
        ("Electronic signatures", "Prepare provider-neutral requests for DocuSign and SignWell without automatic dispatch.", "/contracts/{id}/signatures"),
    )
    return Html(
        head("Developer platform", "Private FastCLM API, OpenAPI schemas, and electronic-signature adapter contracts.", "/developers"),
        Body(
            Header(logo(), Nav(A("API docs", href="/api/v1/docs", cls="public-link"), A("Sign In", href="/login", cls="public-signin"), cls="public-links"), cls="public-nav"),
            Main(
                Div(
                    P("DEVELOPER PLATFORM · API V1", cls="eyebrow"), H1("Build on FastCLM without making contracts public."),
                    P("The integration API is private, versioned, and organisation-scoped. Configure a server-side bearer token, then send the workspace ID explicitly on every data request.", cls="dev-lede"),
                    Div(A("Open Swagger UI", href="/api/v1/docs", cls="button"), A("Open ReDoc", href="/api/v1/redoc", cls="button secondary"), A("Download OpenAPI", href="/api/v1/openapi.json", cls="button secondary"), A("View source", href="https://github.com/predictivelabsai/FastCLM", cls="button secondary"), cls="hero-actions"),
                    Div(Strong("Private by default. "), "Data endpoints return 503 until FASTCLM_API_TOKEN is configured. They then require Authorization: Bearer <token> and X-FastCLM-Organisation: <workspace-id>.", cls="callout"),
                    Div(*[Article(H2(title), P(copy), Code(Span("GET " if route.startswith("/api") else "POST ", cls="method"), route, cls="route"), cls="dev-card") for title, copy, route in resources], cls="dev-grid"),
                    H2("Quick start"),
                    Pre(Code(f'''curl "{settings.public_url}/api/v1/contracts?limit=20" \\
  -H "Authorization: Bearer $FASTCLM_API_TOKEN" \\
  -H "X-FastCLM-Organisation: $FASTCLM_ORGANISATION_ID"'''), cls="code"),
                    H2("Signature providers"),
                    P("The current adapters create reviewable local payloads only. SignWell maps to POST /api/v1/documents with X-Api-Key authentication, draft/test-mode controls, recipients, metadata, and source-version context. DocuSign maps to an envelope draft. Dispatch and webhook processing remain deliberately gated follow-up work.", cls="dev-lede"),
                    P(A("SignWell create-document reference ↗", href="https://developers.signwell.com/reference/createdocument", target="_blank", rel="noopener noreferrer", cls="quiet-link")),
                    cls="dev-wrap",
                ),
            ),
            cls="public-body",
        ),
    )
