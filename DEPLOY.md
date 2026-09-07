# Deploy FastCLM

## Coolify application

- Repository: `predictivelabsai/FastCLM`
- Branch: `main`
- Build pack: Dockerfile
- Container port: `5025`
- Domain: `https://clm.fastsme.com`
- Health check: `/healthz`
- Persistent volume: `/data`

Copy `.env.coolify.sample` into Coolify's environment editor and replace every
blank secret. Generate `FASTCLM_SECRET`, `FASTCLM_API_TOKEN`, and
`FASTCLM_SCIM_TOKEN` independently. Generate a Fernet key for
`FASTCLM_BACKUP_ENCRYPTION_KEY` (for example with
`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`)
and keep it in the same encrypted configuration inventory as the database.
Never commit their values.

SQLite remains the zero-service default. Set `FASTCLM_DATABASE_URL` to a
`postgresql://` connection string to use PostgreSQL; the application applies
the same numbered migrations and uses PostgreSQL-native weighted full-text
search. This selects the authoritative database but does not copy existing
SQLite data, so migrate records and attachments under a separately reviewed
cutover plan before changing an established deployment. `/healthz` reports the
active dialect, migration count, and probe latency. `/metrics` exposes only
aggregate HTTP method/status counters and durations and is suitable for a
private Prometheus scrape through the platform network.

The default `FASTCLM_STORAGE_BACKEND=local` stores source objects and encrypted
backups on the persistent `/data` volume. To use AWS S3 or a compatible object
store, set the bucket, region, optional endpoint, credentials, and prefix shown
in `.env.coolify.sample`, then select `s3`. FastCLM requests AES-256
server-side encryption unless `FASTCLM_S3_KMS_KEY_ID` is set. Existing versions
continue reading from the backend recorded when they were created.

The built-in upload inspection is always enabled. For full antivirus scanning,
point `FASTCLM_CLAMAV_HOST` and `FASTCLM_CLAMAV_PORT` at a private ClamAV daemon;
uploads fail closed when that configured service cannot be reached. The image
includes Tesseract English data for scanned-PDF OCR.

SCIM clients use `https://clm.fastsme.com/scim/v2`, authenticate with
`FASTCLM_SCIM_TOKEN`, and send the target workspace UUID in
`X-FastCLM-Organisation`. Keep the SCIM token separate from the integration API
token so either surface can be rotated or disabled independently.

Set `FASTCLM_REMINDER_SCHEDULER_ENABLED=true` for the single-process container.
The default hourly cycle is retry-safe and records successful or failed
Postmark delivery attempts without sending a duplicate successful reminder on
the same day.

SignWell dispatch requires `SIGNWELL_API_KEY`; incoming events are verified by
reading the claimed document through the authenticated provider API. DocuSign
supports a short-lived `DOCUSIGN_ACCESS_TOKEN` or JWT grant credentials via
`DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`, and `DOCUSIGN_PRIVATE_KEY`, plus
`DOCUSIGN_ACCOUNT_ID`. Configure Connect to send JSON to
`https://clm.fastsme.com/webhooks/docusign` with HMAC enabled, and store the
matching value in `DOCUSIGN_WEBHOOK_SECRET`. Register SignWell's callback as
`https://clm.fastsme.com/webhooks/signwell?token=<SIGNWELL_WEBHOOK_TOKEN>`; the
unguessable token and authenticated provider lookup are both required. Keep both providers in their test
environments until end-to-end evidence retrieval has been reviewed.

Google Auth Platform must have this exact authorised redirect URI:

```text
https://clm.fastsme.com/auth/google/callback
```

## DNS and release check

Create the `clm.fastsme.com` A record pointing at `191.218.164.166`. After DNS
propagates and Coolify provisions TLS, verify:

```bash
curl -fsS https://clm.fastsme.com/healthz
curl -fsS https://clm.fastsme.com/api/v1/health
curl -fsSI https://clm.fastsme.com/
curl -fsSI https://clm.fastsme.com/auth/google
```

Confirm the health response reports `FastCLM`, the anonymous root renders the
landing page, the top-right Sign In remains visible on mobile, and Google sends
the browser to the account chooser with the production callback URI.
