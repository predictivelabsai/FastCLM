# FastCLM architecture

FastCLM is a modular monolith. FastHTML renders the public site and private
workspace, application services enforce tenant and lifecycle rules, SQLite
stores authoritative records, and a mounted FastAPI app exposes a private
integration surface.

```text
FastHTML workspace ─┐
                    ├─ services ─ transaction boundary ─ SQLite
FastAPI /api ────────┘       │
                            ├─ immutable contract versions
Word / PDF ─ extraction ─ editable blocks
                            ├─ deterministic / xAI review
                            ├─ Postmark reminder runner
                            └─ DocuSign / SignWell adapter drafts
```

## Trust boundaries

- Browser routes derive an `Actor` from the signed session and active
  organisation membership.
- Services repeat permission checks and include `organisation_id` in business
  reads and writes.
- Contract lifecycle state changes use `fastclm.lifecycle`; AI cannot invoke
  them.
- API data routes require a server bearer token and an explicit valid
  organisation header. Writes additionally require an authorised workspace
  member ID so role checks and audit attribution are preserved. The API is
  disabled without a configured token.
- Personal xAI keys are encrypted before persistence and never rendered back to
  the browser.
- Uploaded source files receive their own SHA-256 digest; downloads verify the
  stored bytes before serving an attachment.
- Platform-funded review slots are reserved atomically and refunded when the
  provider call fails.
- Uploaded files are stored under tenant and contract UUID paths, outside the
  source tree, and downloaded only after session and tenant checks.

## Contract content

The editable working draft uses ordered typed blocks based on the FastDocs
pattern. A save or document import serialises those blocks into an immutable
version with a SHA-256 checksum. The original uploaded file is retained when
text extraction succeeds. PDF extraction is text-layer based; scanned-document
OCR is deferred.

## External actions

The signature adapters create local, reviewable provider payloads. They do not
send envelopes automatically. The reminder runner is idempotent per obligation,
recipient, kind, and day. Production runs it in-process on a configurable
interval; failed deliveries remain retryable while successful deliveries are
suppressed for the rest of the day.
