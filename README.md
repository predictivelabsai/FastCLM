# FastCLM

[![Production](https://img.shields.io/badge/production-clm.fastsme.com-2457d6)](https://clm.fastsme.com)

FastCLM is an open-source contract lifecycle management workspace for small and
mid-sized organisations. It keeps contracts, counterparties, immutable
versions, clause knowledge, approval decisions, obligations, renewals, and an
append-only audit trail in one focused system.

The default installation needs no external services. It runs on FastHTML with
SQLite, local authentication, deterministic synthetic demonstration data, and
a conservative contract review that works without an AI key. Google OpenID
Connect and a token-gated integration API are optional.

## Implemented product surface

- Organisation-isolated workspaces with owner, administrator, legal,
  approver, and member roles.
- Contract register with search, status filters, counterparties, commercial
  value, dates, ownership, renewal terms, and risk level.
- Reviewed lifecycle transitions from draft through review, approval,
  signature, active, expiry, or termination.
- Immutable text/file version history with SHA-256 integrity checks.
- Approval decisions, due and overdue obligations, clause library, renewal and
  notice-window tracking, and append-only activity history.
- Deterministic risk review that surfaces common commercial terms without
  making legal decisions or changing contract state.
- Google OIDC with state validation and verified-email allowlists.
- Authenticated FastAPI integration routes and generated OpenAPI docs.
- Responsive public landing page and workspace, health/SEO endpoints, Docker,
  and Coolify-ready configuration for `clm.fastsme.com`.

## Run locally

Python 3.13 is recommended.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.sample .env
.venv/bin/python seed.py
.venv/bin/python web_app.py
```

Open `http://localhost:5025`. The sample configuration enables `/auth/test`,
which opens the synthetic Acme Studio workspace without a committed password.
Disable that route in production.

## Verification

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/python -m compileall -q fastclm web_app.py seed.py
```

## Routes

- Public landing: `/`
- Workspace: `/app`
- Contract register: `/contracts`
- Obligations: `/obligations`
- Counterparties: `/counterparties`
- Clause library: `/clauses`
- Audit trail: `/audit`
- API documentation: `/api/v1/docs`
- Health: `/healthz`

## Deployment

The container listens on port `5025`, stores runtime data under `/data`, and
publishes a health check at `/healthz`. See [DEPLOY.md](DEPLOY.md) for the
Coolify variables and DNS/TLS checklist.

## Security

Contract content is private. API data routes are disabled until
`FASTCLM_API_TOKEN` is configured and then require both a bearer token and an
explicit organisation header. Uploaded files are stored outside the source
tree and served only after session and tenant checks. Review findings are
assistive signals, not legal advice.

FastCLM ships with synthetic data only. Do not load production agreements into
an unreviewed demo deployment.

## Licence

MIT. See [LICENSE](LICENSE). FastCLM is part of the open-source
[FastSME](https://fastsme.com) suite.
