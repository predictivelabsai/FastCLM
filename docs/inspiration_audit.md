# FastCLM source-pattern audit

Reviewed: 2026-09-08

This audit records which patterns were examined before and during FastCLM's
implementation, how they map to this product, and where FastCLM deliberately
differs. It is a design comparison, not a claim that third-party source code
was copied.

## Reviewed revisions

- [`sarturko-maker/lq-ai-fork`](https://github.com/sarturko-maker/lq-ai-fork),
  commit `82904157a155ad2926e4ba64447087f7ef1cdb45`
- Local FastDocs, commit `122df68293c742a5a958debfd0550fef14ad7f3e`
- Local FastWiki, commit `3b8e6512fb26debf1cd30cd679ec2cca581dd123`
- Local ai-indurent, commit `34224daeb19ede42193bdee2459976e956d4faa3`

The GitHub repository was cloned afresh into a temporary directory. Review
covered its PRD and honest-state catalogue, streaming agent implementation,
citation engine and tests, skill loader/backend/authoring guide, matter memory,
playbooks, receipts, privacy layer, autonomous brakes, and deployment model.

## Pattern mapping

| Pattern | Reviewed source | FastCLM adaptation | Verification |
|---|---|---|---|
| Matter-scoped persistent chat | lq-ai-fork matter/chat APIs; FastWiki assistant threads | Organisation-scoped threads, confirmed contract roster and concise matter memory | `tests/test_assistant.py` |
| Streaming model and tool events | lq-ai-fork agent stream; FastWiki newline-delimited stream | NDJSON token, tool-start, tool-complete and terminal events; pure ASGI telemetry does not buffer the response | `tests/test_assistant.py`, `web_app.py` |
| Durable execution receipts | lq-ai-fork chat receipts | Tool receipts and final answer persist atomically on the assistant message | `tests/test_assistant.py` |
| Citation verification before rendering | lq-ai-fork citation cascade | Free deterministic consecutive-word verification against an immutable version, with exact character, word and page anchors; Unicode ligatures and PDF line-break hyphenation normalize without losing source offsets | `tests/test_assistant.py`, `tests/test_documents.py` |
| Inspectable skills with progressive disclosure | lq-ai-fork skills registry/backend; ai-indurent prompt manager | Tenant-scoped Markdown skills, concise catalog in context, selected full instructions only, immutable versions and attributable tests | `tests/test_assistant.py`, `tests/test_grounded_matters.py` |
| Conversational skill creator | lq-ai-fork Skill Creator | Triggered meta-skill gathers purpose, triggers, inputs, workflow, output, boundaries and an example before proposing publication | `tests/test_assistant.py` |
| Reusable playbooks | lq-ai-fork playbooks | Preferred/fallback clause playbooks that append a contract version when applied | `tests/test_drafting.py` |
| Block editing and snapshots | FastDocs | Ordered typed contract blocks with immutable checksummed snapshots; restore is represented as a new version rather than replacing history | `tests/test_contracts.py`, `tests/test_drafting.py` |
| Source-aware PDF side pane | ai-indurent | Vendored PDF.js shell behind authenticated tenant/checksum checks, opened from a citation at its page and exact search phrase | `tests/test_documents.py`, Playwright capture 03 |
| Lightweight assistant-first FastHTML shell | FastWiki and the FastSME landing pattern | FastHTML workspace with a central conversation, source/capability rail, public developers/API links and Google entry point | `tests/test_web.py`, Playwright manifest |
| Human-control brakes | lq-ai-fork guarded tools and autonomous brakes | Every model write is a pending proposal. Approval decisions, access changes and signature dispatch are absent from the model tool catalogue | `tests/test_assistant.py`, service permission tests |

## Citation design decision

lq-ai-fork implements a four-stage cascade: exact offsets, tolerant fuzzy
matching, a paraphrase judge, and an optional multi-model ensemble. FastCLM's
requested guarantee is narrower and intentionally deterministic: it proves
that the displayed quoted words occur consecutively in the cited immutable
version. A verified record persists `consecutive_word_match`, confidence 1.0,
word offsets, exact character bounds, and a page where provenance is available.
An unsupported quotation remains visible as `failed`/unverified.

FastCLM does not label a model's legal interpretation as semantically verified.
Adding an LLM judge would consume a separate inference budget and could turn a
probabilistic opinion into an overconfident green badge. The UI and architecture
therefore say exactly what is proven: quote fidelity, not legal correctness.

## Skill design decision

lq-ai-fork's file format supports YAML frontmatter, reference folders,
community catalogs, inference tiers and table-mode columns. FastCLM retains the
portable Markdown instruction body and the important operational sections, but
stores versions in the tenant database so editing, attribution, status and
tests share the same transaction/audit boundary. It supplies only the selected
skill's full instructions to xAI; the rest of the library is represented by a
small capability catalog.

The current editor and conversational creator match the requested use case.
Community git catalogs, inference-tier routing and table-mode skill schemas are
not silently emulated.

## Deliberate non-adoptions

- lq-ai-fork's provider gateway, Ollama air-gap profile and Presidio
  anonymization layer were not adopted because FastCLM was explicitly scoped to
  xAI by default with encrypted BYOK after five included queries. Contract
  sources sent to xAI are disclosed as such; operators needing air-gapped
  inference require a separate provider/privacy roadmap.
- Autonomous background agents were not adopted. FastCLM's contract state,
  signature dispatch, approvals and access controls remain human-originated.
- The Word add-in and Slack/Teams intake bridges were not adopted. FastCLM's
  requested intake is Word/PDF upload and its editing surface is web-native.
- lq-ai-fork's multi-document tabular review was not adopted as a hidden extra.
  FastCLM supports confirmed multi-contract matters and comparisons in chat,
  but does not claim a spreadsheet execution surface.
- Procurement workflows remain excluded by the product brief.

## Licensing and provenance

FastCLM did not vendor lq-ai-fork application code. PDF.js is the only vendored
third-party application asset and remains documented in
`THIRD_PARTY_NOTICES.md`. Product patterns adapted from local sister projects
are reimplemented inside FastCLM's organisation, lifecycle, versioning and
audit boundaries.
