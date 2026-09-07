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
blank secret. Generate `FASTCLM_SECRET` and `FASTCLM_API_TOKEN` independently.
Never commit their values.

Google Auth Platform must have this exact authorised redirect URI:

```text
https://clm.fastsme.com/auth/google/callback
```

## DNS and release check

Create the `clm.fastsme.com` A record pointing at `191.218.164.166`. After DNS
propagates and Coolify provisions TLS, verify:

```bash
curl -fsS https://clm.fastsme.com/healthz
curl -fsSI https://clm.fastsme.com/
curl -fsSI https://clm.fastsme.com/auth/google
```

Confirm the health response reports `FastCLM`, the anonymous root renders the
landing page, the top-right Sign In remains visible on mobile, and Google sends
the browser to the account chooser with the production callback URI.
