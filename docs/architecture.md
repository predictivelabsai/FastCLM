# FastCLM architecture

FastCLM is a modular monolith. FastHTML renders the public site and private
workspace, application services enforce tenant and lifecycle rules, SQLite
stores authoritative records, and a mounted FastAPI app exposes a private
integration surface.

```text
FastHTML AI cockpit ─┐
                     ├─ services ─ transaction boundary ─ SQLite
FastAPI /api ─────────┘       │
                              ├─ conversations + proposed actions
Word / PDF ─ extraction ──────┼─ immutable contract versions
                              ├─ versioned Markdown skills
                              ├─ deterministic / xAI review
                              ├─ Postmark reminder runner
                              └─ DocuSign / SignWell adapter drafts
```

## Trust boundaries

- Browser routes derive an `Actor` from the signed session and active
  organisation membership.
- Services repeat permission checks and include `organisation_id` in business
  reads and writes.
- Contract lifecycle state changes use `fastclm.lifecycle`. The assistant can
  propose a permitted action, but a user must confirm it and the existing
  service permission and lifecycle checks still run.
- API data routes require a server bearer token and an explicit valid
  organisation header. Writes additionally require an authorised workspace
  member ID so role checks and audit attribution are preserved. The API is
  disabled without a configured token.
- Personal xAI keys are encrypted before persistence and never rendered back to
  the browser.
- Uploaded source files receive their own SHA-256 digest; downloads verify the
  stored bytes before serving an attachment. Inline PDF viewing repeats the
  same session, tenant, path, media-type, and digest checks.
- Platform-funded assistant/review slots are reserved atomically and refunded when the
  provider call fails.
- Uploaded files are stored under tenant and contract UUID paths, outside the
  source tree, and downloaded only after session and tenant checks.

## Contract content

The editable working draft uses ordered typed blocks based on the FastDocs
pattern. A save or document import serialises those blocks into an immutable
version with a SHA-256 checksum. The original uploaded file is retained when
text extraction succeeds. PDF extraction is text-layer based; scanned-document
OCR is deferred.

## Assistant, sources, and skills

`/app` is the primary workspace. It persists organisation-scoped conversations
and retrieves only the newest immutable version of contracts in the active
workspace. Contract text is fenced as untrusted evidence in the xAI prompt;
answers carry source-version cards that link back to the record or open the
authenticated PDF.js side pane.

Write-like model output is stored as a pending `assistant_action`. Nothing is
executed until a signed-in user confirms it. Confirmation calls the same
`ContractService` methods used by the conventional screens, so role checks,
lifecycle gates, immutable versions, and audit events are not bypassed.

Skills are organisation-scoped Markdown instructions. Owner, admin, and legal
roles can edit them. Every save inserts an immutable `skill_versions` row while
the selected current version is supplied transparently to the assistant.

## External actions

The signature adapters create local, reviewable provider payloads. They do not
send envelopes automatically. The reminder runner is idempotent per obligation,
recipient, kind, and day. Production runs it in-process on a configurable
interval; failed deliveries remain retryable while successful deliveries are
suppressed for the rest of the day.
