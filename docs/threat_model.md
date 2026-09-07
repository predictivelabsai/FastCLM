# FastCLM threat model

## Protected assets

Contract files and extracted text, commercial metadata, approval decisions,
counterparty contacts, per-user provider keys, session secrets, integration
tokens, and audit history.

## Principal risks and current controls

- **Cross-tenant access:** organisation scoping in service/API queries and
  tenant-checked attachment downloads.
- **Unauthorised writes:** signed sessions, CSRF tokens, role permissions, and
  service-boundary checks.
- **Lifecycle bypass:** central transition catalogue plus an approval
  prerequisite for activation.
- **Document replacement:** immutable snapshots, original attachment retention,
  and SHA-256 checksums.
- **Model authority:** review is advisory and cannot approve, sign, activate, or
  terminate.
- **Secret exposure:** environment-only fleet secrets and encrypted per-user
  BYOK values that are never returned to the browser.
- **Abusive model spend:** atomic five-query allowance and BYOK preference.
- **External side effects:** signature requests are local drafts; reminders are
  idempotent and require a configured server token.

## Production work still required

Add malware scanning, OCR sandboxing, object-store encryption, backup/restore
exercises, CSP/security headers at the proxy, rate limiting, configurable RBAC,
webhook verification, secret rotation procedures, and an external penetration
test before handling sensitive production agreements.
