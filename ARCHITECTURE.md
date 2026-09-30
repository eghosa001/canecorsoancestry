# Architecture

## Active production stack

Cane Corso Ancestry is a server-rendered Django application with exactly three infrastructure responsibilities:

```
Browser
  |
  v
Render (Django + Gunicorn + WhiteNoise)
  |
  +----> Aiven PostgreSQL
  |
  +----> private Cloudflare R2 media gateway ----> R2 bucket
```

### Render

Render runs Django and serves static files directly.

- Python 3.13
- Django 5.2
- Gunicorn: one worker, two threads
- WhiteNoise for `/static/`
- public URL: `https://canecorsoancestry.onrender.com`
- `/healthz/` for service health checks

There is no Cloudflare application proxy or Render-origin gate.

### Aiven PostgreSQL

Aiven is the only production relational database.

Django uses the private application schema:

`django_app`

Production search path:

`django_app,public`

`pg_trgm` supports scalable fuzzy/duplicate matching.

Django authentication, sessions, moderation and application data all live in this database.

### Cloudflare R2

R2 is the only durable object store for uploaded media/evidence.

The Worker at `canecorsoancestry-edge.aighewieghosa111.workers.dev` is intentionally narrow: it is an authenticated R2 media gateway only. It does not proxy Django, host the site, serve static assets, manage a custom domain or route application traffic.

Supported Worker routes:

- `/healthz/` — gateway health
- `/_r2/*` — HMAC-authenticated backend R2 operations
- `/_media/*` — short-lived signed media delivery

All other Worker paths return 404.

Django authorizes media access before redirecting the browser to a short-lived R2 media URL.

## Django applications

### `core`
Site shell, homepage, shared navigation, media authorization and dashboard.

### `accounts`
Member profile, member workspaces and moderation workflows.

### `registry`
Canonical dog, kennel, litter, image, health, source and external-registration records.

### `pedigrees`
Pedigree traversal, repeated-ancestor analysis, common-ancestor analysis, COI calculations and virtual mating.

## Deployment

The active deployment files are:

- `render.yaml`
- `wrangler.r2.toml`
- `.github/workflows/test.yml`
- `.github/workflows/render-r2-build.yml`
- `.github/workflows/cloudflare-media.yml`
- `.github/workflows/ui-smoke.yml`
- `.github/workflows/production-seed.yml`
- `.github/workflows/sync-bellissimo-media.yml`

Normal code pushes deploy Render after checks pass. The R2 gateway deploys only when its Worker/configuration changes.

## Media storage

Render's filesystem is ephemeral, so user media never depends on local disk.

`core.r2_gateway_storage.CloudflareR2GatewayStorage` signs storage operations using `DJANGO_SECRET_KEY` and sends them to the private R2 gateway.

`core.media_views.media_file` applies Django authorization and then returns a short-lived signed R2 delivery URL.

## Removed legacy paths

The repository no longer contains runtime/deployment paths for:

- Supabase
- Google Cloud Run
- Railway
- GitHub Pages frontend preview
- Cloudflare application proxy/custom-domain routing
- generic S3 provider configuration
- Sentry integration
- completed one-time database/media migration endpoints

## Scalability

For a catalog approaching 100,000 dogs, concentrate on:

- Aiven database/storage limits;
- indexes and query plans;
- bounded pedigree traversal;
- pagination and selective search;
- low database connection counts;
- R2 object growth.

The app remains portable because Django uses standard PostgreSQL and stores media keys independently from the object provider.
