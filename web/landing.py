"""FastCLM public product landing page."""
from fasthtml.common import *

from fastclm.web.ui import logo, product_mock

from .seo import DESCRIPTION, seo_meta


def _head() -> Head:
    return Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1, viewport-fit=cover"),
        Meta(name="theme-color", content="#2457d6"),
        Meta(name="description", content=DESCRIPTION),
        Title("Open contract management · FastCLM"),
        *seo_meta(path="/", title="FastCLM · Open contract lifecycle management", description=DESCRIPTION),
        Link(rel="icon", href="/static/favicon.svg", type="image/svg+xml"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        Link(rel="stylesheet", href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,600&display=swap"),
        Link(rel="stylesheet", href="/static/app.css?v=2"),
    )


def landing_page() -> Html:
    features = (
        ("One contract record", "Keep Word and PDF originals, editable blocks, counterparties, commercial facts, and immutable versions together."),
        ("Governed lifecycle", "Move from draft to review, approval, signature, and active management through explicit, audited gates."),
        ("Dates that do work", "Track obligations, notice windows, renewals, expiry, and accountable owners before deadlines become surprises."),
    )
    return Html(
        _head(),
        Body(
            Header(
                logo(),
                Nav(
                    A("Developers", href="/developers", cls="public-link"),
                    A("API", href="/api/docs", cls="public-link"),
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
                        P(DESCRIPTION, cls="hero-copy"),
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
                    Div(A("Developer guide", href="/developers", cls="button"), A("Open API docs", href="/api/docs", cls="button secondary"), cls="hero-actions"),
                    cls="public-section",
                ),
            ),
            Footer(Span("FastCLM is part of the open-source FastSME suite."), A("View all products", href="https://fastsme.com/products", cls="quiet-link"), cls="public-footer"),
            cls="public-body",
        ),
    )
