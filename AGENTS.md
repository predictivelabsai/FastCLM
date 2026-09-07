# FastCLM repository guidelines

FastCLM is a Python 3.13 FastHTML application with a same-process FastAPI
integration surface. Keep browser routes thin, contract decisions in services,
permission checks server-side, and SQL inside the database/service boundary.

- Every business record must be scoped to an organisation.
- Contract lifecycle changes must use the reviewed transition catalogue. Do not
  update lifecycle state directly from a route.
- AI or deterministic review may identify, explain, compare, and draft. It may
  never approve, sign, activate, terminate, or change access on its own.
- Preserve every contract version. New content creates a version; it never
  overwrites prior text or attachment metadata.
- Store authoritative monetary values as decimal-compatible text, never binary
  floating point.
- Append audit events for mutations and approval decisions.
- Use additive numbered migrations and deterministic synthetic fixtures.
- Keep SQLite working without external services.
- Never commit `.env`, credentials, real contracts, uploaded documents,
  databases, browser state, or generated local artifacts.

Run before handing work off:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/python -m compileall -q fastclm web_app.py seed.py
git diff --check
```

Keep `docs/product_roadmap.md` synchronized with delivered and deferred scope.
