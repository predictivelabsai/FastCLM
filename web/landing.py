"""FastCLM public product landing page."""
from fasthtml.common import *

from fastclm.web.ui import logo

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
        Link(rel="stylesheet", href="/static/app.css?v=4"),
        Style("""
.pricing-section{max-width:1100px;margin:0 auto;padding:72px 24px;scroll-margin-top:80px}
.pricing-section .eyebrow{margin-bottom:8px}
.pricing-section h2{font-size:32px;letter-spacing:-.03em;margin:8px 0 12px}
.pricing-section>.lede{color:var(--muted,#667085);line-height:1.65;max-width:720px;margin:0}
.pricing-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:32px}
.pricing-card{border:1px solid var(--line,#e7eaf0);border-radius:18px;padding:26px;background:#fff}
.pricing-card .eyebrow{font-size:10px;font-weight:750;letter-spacing:.1em;text-transform:uppercase;color:#2457d6}
.pricing-card h3{font-size:22px;margin:14px 0 8px}
.pricing-price{font-size:36px;font-weight:750;letter-spacing:-.03em;margin:8px 0 12px}
.pricing-card p:last-child{color:var(--muted,#667085);line-height:1.6;margin:0}
@media(max-width:760px){.pricing-grid{grid-template-columns:1fr}}
"""),
    )


def landing_page() -> Html:
    features = (
        ("Watch the work", "Stream answers and tool activity live. Durable receipts show what ran, while exact quotes are verified word by word against the source version."),
        ("Build skills by talking", "Describe a workflow in conversation. The Skill Creator asks for what is missing, drafts readable Markdown, and waits for your approval to publish."),
        ("Human-controlled action", "Let the assistant prepare lifecycle work while approvals, signatures, activation, termination, and access remain explicit human decisions."),
    )
    return Html(
        _head(),
        Body(
            Header(
                logo(),
                Nav(
                    A("Pricing", href="#pricing", cls="public-link"),
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
                        H1("Ask your contracts what happens next."),
                        P(DESCRIPTION, cls="hero-copy"),
                        Div(A("Create your workspace", href="/signup", cls="button"), A("Explore the API", href="/developers", cls="button secondary"), cls="hero-actions"),
                        P("MIT licensed · SQLite included · Your documents stay private", cls="proof"),
                    ),
                    Div(Img(src="/static/product-demo.gif", alt="FastCLM AI assistant, source-aware PDF viewer, skills editor, and contract workspace walkthrough", cls="hero-demo"), cls="hero-product"),
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
                    P("PRICING", cls="eyebrow"),
                    H2("Simple pricing for every FastSME product."),
                    P("Every Fast* product uses the same two options: bring your own cloud for free, or host with us for €1 per month.", cls="lede"),
                    Div(
                        Article(
                            P("BYOC", cls="eyebrow"),
                            H3("Bring Your Own Cloud"),
                            P("Free", cls="pricing-price"),
                            P("Self-host on your own infrastructure or cloud. Full control of data and upgrades. No per-seat platform fee."),
                            cls="pricing-card",
                        ),
                        Article(
                            P("HOSTED", cls="eyebrow"),
                            H3("Host with us"),
                            P("€1 / month", cls="pricing-price"),
                            P("We run the product for you on FastSME-managed infrastructure. €1 per product per month."),
                            cls="pricing-card",
                        ),
                        cls="pricing-grid",
                    ),
                    id="pricing",
                    cls="pricing-section",
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
