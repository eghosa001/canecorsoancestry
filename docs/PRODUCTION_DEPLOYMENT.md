# Production deployment

## Active architecture

Only these services are part of the live application:

1. **Render** — Django web application and static files
2. **Aiven PostgreSQL** — production relational database
3. **Cloudflare R2** — durable uploaded media

Current app URL:

`https://canecorsoancestry.onrender.com`

Current R2 media gateway:

`https://canecorsoancestry-edge.aighewieghosa111.workers.dev`

No custom domain is required to run or review the application.

## Render

The Render service is defined by `render.yaml`.

Required private environment values already configured on Render:

- `DATABASE_URL` — Aiven PostgreSQL service URI
- `DJANGO_SECRET_KEY` — Django secret key

Repository-managed settings include:

- `DJANGO_SETTINGS_MODULE=config.settings.render`
- `DJANGO_DB_SCHEMA=django_app`
- `DJANGO_DB_SSLMODE=require`
- `DJANGO_DB_EXTRA_SCHEMAS=public`
- `DJANGO_ALLOWED_HOSTS=.onrender.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://canecorsoancestry.onrender.com`
- `SITE_URL=https://canecorsoancestry.onrender.com`
- R2 gateway URL and media TTL
- Python 3.13.15

Render runs migrations before Gunicorn starts and uses `/healthz/` as the health check.

## Aiven

Aiven service: `pg-e8bf844`.

The completed migration has already been verified. Aiven is the production source of truth.

The application uses:

- schema `django_app`
- TLS
- search path `django_app,public`
- `pg_trgm`

Do not reintroduce a Supabase migration workflow unless a new migration is explicitly required.

## Cloudflare R2

R2 bucket:

`canecorsoancestry-media`

The R2 Worker is intentionally media-only. It does not proxy Render or own an application domain.

Required GitHub Actions secrets:

- `CLOUDFLARE_API_TOKEN`
- `DJANGO_SECRET_KEY`

The workflow `.github/workflows/cloudflare-media.yml`:

- verifies/creates the R2 bucket;
- deploys `src/r2-media.js` using `wrangler.r2.toml`;
- verifies the media gateway health endpoint;
- verifies unsigned private R2 requests are rejected.

## Normal deployment flow

For ordinary application changes:

1. push/merge to `main`;
2. GitHub CI runs;
3. Render deploys after checks pass.

For R2 gateway changes, the dedicated Cloudflare R2 workflow also runs.

There is no need to run a database migration-copy workflow, Render API bootstrap workflow, GitHub Pages deployment, Cloudflare zone workflow or custom-domain cutover workflow.

## Manual data workflows

Two manual workflows remain because they are useful current-stack maintenance tools:

- **Seed production Bellissimo data** — writes verified seed data to Aiven.
- **Sync Bellissimo media to R2** — uploads verified media to R2 and attaches the corresponding Aiven metadata.

They should be run only intentionally.

## Custom domain later

A custom domain is optional and intentionally outside the current runtime.

When a domain is purchased, connect it directly to Render first. Do not reintroduce a Cloudflare application proxy unless there is a concrete need for it.

## Health checks

Expected:

- `https://canecorsoancestry.onrender.com/` → 200
- `https://canecorsoancestry.onrender.com/healthz/` → 200
- `https://canecorsoancestry-edge.aighewieghosa111.workers.dev/healthz/` → 200
- unsigned `/_r2/*` requests → 403
