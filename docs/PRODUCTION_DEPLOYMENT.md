# Production deployment

## Active architecture

The live application currently uses:

1. **Cloudflare Workers site edge** — public website endpoint and cache/warm-up layer
2. **Northflank** — Django application origin
3. **Supabase PostgreSQL** — canonical relational database
4. **Cloudflare R2** — durable media storage through the R2 media Worker

Public site:

`https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`

Northflank origin:

`https://web--canecorsoancestry--4w9gl8jxj4yr.code.run`

R2 media gateway:

`https://canecorsoancestry-edge.aighewieghosa111.workers.dev`

No custom domain is configured.

## Northflank

The application runs with:

`DJANGO_SETTINGS_MODULE=config.settings.northflank`

The current deployment workflow is:

`.github/workflows/provision-northflank.yml`

It builds the exact GitHub commit, deploys it to the Northflank service and verifies the origin health/application endpoints.

## Supabase PostgreSQL

GitHub Actions use the `SUPABASE_DATABASE_URL` secret and derive a reachable session-pooler URL with:

`scripts/discover_supabase_session_pooler.py`

Django uses:

- schema `django_app`;
- TLS;
- extra schemas `extensions,public`.

## Cloudflare site edge

Configuration:

- `src/site-edge.js`
- `wrangler.site.toml`
- `.github/workflows/cloudflare-site-edge.yml`

The edge proxies to Northflank, caches eligible public GET responses, keeps private/authenticated routes uncached and handles origin warm-up/readiness.

## Cloudflare R2

R2 bucket:

`canecorsoancestry-media`

Configuration:

- `src/r2-media.js`
- `wrangler.r2.toml`
- `.github/workflows/cloudflare-media.yml`

The media Worker handles authenticated backend R2 operations and signed media delivery.

## Required GitHub secrets

Current production workflows use:

- `NORTHFLANK_API_TOKEN`
- `SUPABASE_DATABASE_URL`
- `DJANGO_SECRET_KEY`
- `CLOUDFLARE_API_TOKEN`

## Deployment flow

For ordinary application changes:

1. merge/push to `main`;
2. focused CI runs only for the changed surface;
3. relevant Django changes trigger `provision-northflank.yml`;
4. Northflank builds and deploys the exact commit.

For site-edge changes, `cloudflare-site-edge.yml` deploys the public Worker.

For R2 Worker/config changes, `cloudflare-media.yml` deploys the media Worker.

Data import/seed/media-sync workflows remain explicit maintenance operations.

## Expected health endpoints

- public edge: `/__edge/health`
- Northflank Django: `/healthz/`
- R2 media Worker: `/healthz/`
