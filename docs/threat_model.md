# FastCLM threat model

## Protected assets

Contract files and extracted text, commercial metadata, approval decisions,
counterparty contacts, per-user provider keys, session secrets, integration
tokens, invitation links, SCIM identity mappings, and audit history.

## Principal risks and current controls

- **Cross-tenant access:** organisation scoping in service/API queries and
  tenant-checked attachment downloads.
- **Unauthorised writes:** signed sessions, CSRF tokens, role permissions, and
  service-boundary checks.
- **Access-management takeover:** hashed expiring invitation tokens, invited
  email matching, fixed role choices, owner protection, and audited member
  changes.
- **Cross-tenant provisioning:** a separate SCIM bearer token plus mandatory
  organisation header, tenant-scoped IDs, and owner-safe deprovisioning.
- **Lifecycle bypass:** central transition catalogue plus an approval
  prerequisite for activation.
- **Document replacement:** immutable snapshots, original attachment retention,
  and SHA-256 checksums.
- **Hostile uploads:** type/magic checks, active-PDF rejection, bounded Word
  archive expansion, executable/macro rejection, an antivirus test signature,
  and optional fail-closed ClamAV scanning before storage.
- **Storage disclosure/loss:** tenant-prefixed object keys, local path
  containment, S3 server-side encryption, application-encrypted backups, and
  digest verification before serving or backing up sources.
- **Model authority:** review is advisory and cannot approve, sign, activate, or
  terminate.
- **Memory poisoning or scope drift:** matter memory and its contract links are
  visible proposals until a signed-in user confirms them; linked contract IDs
  are revalidated against the active tenant before saving or retrieval.
- **Untraceable skill changes:** conversational tests preserve the tested skill
  version and example contract, while refinements append an attributable
  immutable version only after confirmation.
- **Silent negotiated-text changes:** redline proposal and acceptance are
  separate audited actions; accepted wording, library insertion, templates,
  and playbooks append immutable versions rather than replacing history.
- **Cross-tenant collaboration:** block references, mentioned users,
  assignees, template clauses, and playbook clauses are revalidated against the
  active organisation at the service boundary.
- **Secret exposure:** environment-only fleet secrets and encrypted per-user
  BYOK values that are never returned to the browser.
- **Abusive model spend:** atomic five-query allowance and BYOK preference.
- **External side effects:** signature requests remain local drafts until a
  separate human-confirmed dispatch. SignWell events are verified by provider
  lookup, DocuSign events by exact-body HMAC, duplicate events are suppressed,
  and completed files are scanned and checksummed. Reminders are idempotent and
  require a configured server token.

## Production work still required

Add OCR process isolation, automated backup restore exercises, ClamAV signature
operations, CSP/security headers at the proxy, rate limiting, configurable RBAC,
secret rotation procedures, and an external penetration
test before handling sensitive production agreements.
