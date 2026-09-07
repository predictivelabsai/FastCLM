# FastCLM architecture

FastCLM is a modular monolith. FastHTML renders the public site and private
workspace, application services enforce tenant and lifecycle rules, SQLite or
PostgreSQL stores authoritative records, and a mounted FastAPI app exposes a private
integration surface.

```text
FastHTML AI cockpit ─┐
                     ├─ services ─ transaction boundary ─ SQLite / PostgreSQL
FastAPI /api ─────────┘       │
                              ├─ conversations + durable tool receipts
                              ├─ page/character citations + proposed actions
                              ├─ confirmed multi-contract matter memory
Word / PDF ─ extraction ──────┼─ immutable contract versions
       │ OCR + scan            ├─ local / S3-compatible source objects
       └ page provenance       ├─ retention + encrypted tenant backups
                              ├─ versioned Markdown skills
                              ├─ redlines + collaborative review work
                              ├─ staged approval runs + delegation evidence
                              ├─ templates + fallback playbooks
                              ├─ checksum-bound counsel review evidence
                              ├─ deterministic / xAI review
                              ├─ Postmark templates + escalation runner
                              └─ DocuSign / SignWell execution + evidence

SCIM /scim/v2 ─ bearer + organisation ─ memberships + audit
Health / metrics ─ database probe + privacy-safe HTTP counters/logs
```

The repository adapter preserves the same parameterised service queries on
both dialects. Migrations are numbered once, with a PostgreSQL override only
where the implementation must be dialect-native. Contract search uses FTS5 on
SQLite and a weighted generated `tsvector` plus GIN index on PostgreSQL; both
apply the active organisation before returning ranked contract identifiers.
HTTP metrics deliberately use only method and status labels, avoiding tenant,
contract, path, and query-string cardinality. Structured request logs use the
matched route template and request ID, never the URL query or request body.

## Trust boundaries

- Browser routes derive an `Actor` from the signed session and active
  organisation membership.
- Services repeat permission checks and include `organisation_id` in business
  reads and writes.
- Contract lifecycle state changes use `fastclm.lifecycle`. The assistant can
  propose a permitted action, but a user must confirm it and the existing
  service permission and lifecycle checks still run.
- Approval entry creates an ordered run from a tenant policy. Stage decisions
  enforce quorum, eligible roles or named assignees, requester exclusions, and
  optional distinct prior approvers. A bounded delegate acts for an eligible
  delegator while both identities remain in the evidence record. Only final
  workflow completion advances to signature through the lifecycle catalogue.
- API data routes require a server bearer token and an explicit valid
  organisation header. Writes additionally require an authorised workspace
  member ID so role checks and audit attribution are preserved. The API is
  disabled without a configured token.
- Personal xAI keys are encrypted before persistence and never rendered back to
  the browser.
- Invitation bearer values are shown only in the outbound link; only their
  SHA-256 digests are stored. Acceptance requires the invited email identity,
  and role/removal operations cannot change or remove the workspace owner.
- SCIM user calls require an independent bearer token and explicit organisation
  ID. Provisioning IDs and external IDs are tenant-scoped; SCIM display names
  do not overwrite a shared user's global profile, and deprovisioning cannot
  remove an owner.
- Uploaded source files receive their own SHA-256 digest; downloads verify the
  stored bytes before serving an attachment. Inline PDF viewing repeats the
  same session, tenant, object-key, media-type, and digest checks.
- Uploads pass conservative type, active-content, archive, and test-signature
  checks before persistence. A configured ClamAV service is a fail-closed
  additional scanner.
- Local objects use atomic replacement. S3-compatible objects request AES-256
  server-side encryption or a configured KMS key. Each version records its
  backend so storage can be changed without stranding older sources.
- Retention is tenant-controlled, disabled by default, and applies only to
  aged source attachments for expired or terminated contracts. Encrypted
  workspace backups include records and checksum-verified source bytes.
- Platform-funded assistant/review slots are reserved atomically and refunded when the
  provider call fails.
- Uploaded files are stored under tenant and contract UUID paths, outside the
  source tree, and downloaded only after session and tenant checks.

## Contract content

The editable working draft uses ordered typed blocks based on the FastDocs
pattern. A save or document import serialises those blocks into an immutable
version with a SHA-256 checksum. The original uploaded file is retained when
text extraction succeeds. PDFs retain per-page extracted text; pages without a
usable text layer are rendered for Tesseract OCR and marked on the version.

## Assistant, sources, and skills

`/app` is the primary workspace. The browser reads newline-delimited JSON from
`/assistant/stream`, rendering xAI token deltas and tool lifecycle events as
they arrive. Completed tool receipts, the final answer, citations, and any
proposals are committed together so a reload shows the durable result.

Retrieval considers only the newest immutable version of contracts in the
active organisation, further limited to a matter's confirmed contract links
when present. Contract text is fenced as untrusted evidence in the xAI
prompt. The model must put a short verbatim quote in each citation marker. A
server-side verifier normalises case, punctuation, and apostrophes, then looks
for those words consecutively in the cited version. Only a match receives the
verified badge, word offsets, exact character bounds, and a page number when
page provenance exists; a non-match remains visible as unverified. The PDF.js
side pane searches the original PDF for the exact quote. This proves the quote
exists in that source version, not that an interpretation is legally correct.

Write-like model output is stored as a pending `assistant_action`. Nothing is
executed until a signed-in user confirms it. Confirmation calls the same
`ContractService` methods used by the conventional screens, so role checks,
lifecycle gates, immutable versions, and audit events are not bypassed.

Skills are organisation-scoped Markdown instructions. Owner, admin, and legal
roles can edit them. Every save inserts an immutable `skill_versions` row while
the selected current version is supplied transparently to the assistant. The
Skill Creator is selected from conversational intent, asks for missing design
details, and emits a `create_skill` proposal only after it has purpose, triggers,
inputs, workflow, output, boundaries, and an example. The existing role check
still controls whether that draft can be published.

Each assistant thread can act as a separate matter. Contract links and a short
factual memory are written only through a confirmed proposal and are included
in later prompts. A selected skill can be exercised against an example
contract in conversation; confirmed test records preserve the skill version,
expected and observed outcomes, and verdict. Refinement creates a new immutable
skill version rather than rewriting test history.

## Collaborative drafting

Clause-library insertion and accepted redlines are restricted to draft/review
contracts and immediately append a checksummed version. Redline proposals keep
original and proposed wording plus a deterministic unified diff; proposing and
accepting are separate audited decisions. Comments, tenant-validated mentions,
and assignments remain business records after resolution or completion.
Templates assemble ordered blocks into a new draft, while negotiation
playbooks group preferred clauses and their explicit fallbacks.

## Legal content governance

The bundled UK/EU clauses are generic scaffolding and start unreviewed. A
workspace may create a review request naming the exact clauses, jurisdiction,
scope, and intended reviewer. When a real external decision returns, an owner,
admin, or legal member records the lawyer's identity, organisation,
qualification, jurisdiction, decision, scope notes, and a controlled evidence
reference, with an explicit qualification attestation. The immutable evidence
row binds to a SHA-256 checksum of the preferred wording, fallback, and review
guidance. Current status is derived from that checksum, so later wording cannot
inherit an older approval. FastCLM records this evidence; it does not verify a
professional register or turn generic content into legal advice by itself.
The assistant sees review status and may propose a scoped review request, but
only the direct evidence workflow can record a returned counsel decision.

## External actions

The signature adapters create local drafts frozen to an immutable contract
version. A signed-in lifecycle manager must separately confirm dispatch.
SignWell webhook claims are checked against its authenticated document API;
DocuSign Connect messages require an HMAC over the exact body. Verified events
and recipient states are tenant-scoped and idempotent. Completion retrieves the
provider PDF with its audit page, scans and checksums it, and stores it beside
the evidence trail. Reminder candidates respect each owner's opt-out,
due-soon window, and overdue cadence. Tenant templates render locally or by
Postmark alias. Escalation rules target a person or every member of a role and
use a fixed threshold date, so a successful escalation is sent only once while
failures remain retryable. Production runs the worker in-process on a
configurable interval.
