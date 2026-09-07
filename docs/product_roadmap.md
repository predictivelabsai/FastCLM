# FastCLM product roadmap

Updated: 2026-09-08

## Delivered foundation

- Multi-tenant workspaces, local accounts, Google OIDC, fixed permission roles,
  CSRF protection, and append-only audit events.
- Expiring team invitations, owner-safe role administration, organisation
  switching, and tenant-scoped SCIM 2.0 user provisioning/deprovisioning.
- Searchable contract register, counterparties, commercial dates and values,
  reviewed lifecycle transitions, approvals, obligations, renewals, and expiry
  visibility.
- Word `.docx`, text, Markdown, and text-layer PDF ingestion; FastDocs-style
  editable blocks; immutable checksummed versions.
- UK/EU starter clause library and assistive deterministic/xAI review.
- Five per-user platform-funded xAI queries, shared by assistant and review,
  followed by encrypted BYOK.
- Idempotent, retry-safe Postmark obligation reminder scheduler.
- Reviewable DocuSign and SignWell payload stubs.
- Private integration API with fleet-compatible discovery, pagination,
  generated documentation and committed OpenAPI; Docker/Coolify assets; and
  responsive public/product surfaces.
- Assistant-first legal-work cockpit with persistent conversations, streamed
  tokens and tool activity, durable execution receipts, organisation-scoped
  retrieval, and confirmation-gated write proposals.
- Word-level citation verification against immutable source versions, with
  unsupported quotations explicitly marked unverified and exact-quote search
  in the authenticated PDF.js pane.
- Transparent, editable Markdown skills library with five starter contract
  capabilities, conversational skill creation, human-reviewed publication,
  and immutable, attributable version history.
- Deterministic Playwright product capture, validated screenshot manifest,
  README walkthrough, and the same animated walkthrough on the landing page.
- Scanned-PDF OCR with page-level provenance, pre-persistence structural and
  optional ClamAV scanning, local/S3-compatible private object storage,
  opt-in terminal-contract source retention, and encrypted tenant backups.
- Page- and character-anchored citation verification, confirmation-gated
  multi-contract matter memory, and conversational skill tests/refinements
  against example agreements with attributable results and versions.
- Clause and fallback insertion, reviewable redline diffs, comments and member
  mentions, review assignments, template-based first drafts, and reusable
  negotiation playbooks; accepted wording always creates a version.
- Configurable ordered approval policies with stage quorums, role and named
  assignee eligibility, requester exclusion, separation of duties, bounded
  delegation, and attributable direct/delegated decision evidence.
- Human-confirmed SignWell and DocuSign dispatch against a frozen version,
  authenticated provider/webhook verification, signer status, idempotent event
  evidence, and scanned/checksummed completed-PDF retrieval.
- Per-user reminder opt-out, due-soon windows and overdue cadence; tenant-owned
  local/Postmark-alias templates; and auditable role/person escalation paths
  with retry-safe, one-time threshold delivery.
- SQLite/PostgreSQL repository parity through a shared migration ledger and
  dialect-native full-text indexes, with the complete test suite verified on
  isolated per-test PostgreSQL 16 databases as well as SQLite;
  weighted organisation-scoped prefix search; database-aware health,
  request IDs, privacy-safe structured request logs, and Prometheus counters.
- Counsel-review governance with scoped clause/jurisdiction requests,
  qualification attestation, immutable reviewer and evidence records, and
  wording-checksum status that prevents an edited clause inheriting an older
  decision; the assistant can prepare a request for confirmation but cannot
  create counsel evidence or mark wording approved. Portable review packs bind
  the requested scope to the exact clause text and checksums.
- Twenty-four confirmation-gated assistant tools span contract operations,
  drafting, signature preparation, approval configuration, notifications,
  retention, backups, and counsel requests, while human-only decisions and
  external dispatch remain deliberately outside the model catalogue.
- Auditable source-pattern comparison against pinned lq-ai-fork, FastDocs,
  FastWiki, and ai-indurent revisions; deterministic citation evidence names
  its verification method and tolerates Unicode ligatures and line-end PDF
  hyphenation while preserving exact immutable-source character offsets.

## Next production increments

- Jurisdiction-specific legal content reviewed by qualified counsel. Current
  UK/EU material is generic product scaffolding and not legal advice. The
  product workflow is ready, but actual external counsel review and evidence
  must be supplied by the operator.
