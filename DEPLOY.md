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
`FASTCLM_SCIM_TOKEN` independently.
Never commit their values.

SCIM clients use `https://clm.fastsme.com/scim/v2`, authenticate with
`FASTCLM_SCIM_TOKEN`, and send the target workspace UUID in
`X-FastCLM-Organisation`. Keep the SCIM token separate from the integration API
token so either surface can be rotated or disabled independently.

Set `FASTCLM_REMINDER_SCHEDULER_ENABLED=true` for the single-process container.
The default hourly cycle is retry-safe and records successful or failed
Postmark delivery attempts without sending a duplicate successful reminder on
the same day.

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
