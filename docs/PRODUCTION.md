# Production Operations

## Final production architecture

Cane Corso Ancestry uses **Cloudflare + Supabase**.

- Application runtime: Cloudflare Containers running Django/Gunicorn
- Edge router and static assets: Cloudflare Workers + Workers Static Assets
- Database: Supabase PostgreSQL project `wsntfvpcqloqzwgmsfaz` in `eu-north-1`
- Database connectivity: Supabase Session Pooler from the container
- Media/evidence: private Cloudflare R2 bucket `canecorsoancestry-media`
- DNS/TLS/application origin: Cloudflare Custom Domain on `canecorsoancestry.com`

Railway is not part of the final architecture. It may remain temporarily only as a rollback/source environment until data and media cutover are verified.

## Why Containers instead of Python Workers

The Django application was tested on Cloudflare Python Workers. The package, bindings, Supabase migrations and R2 deployment all worked, but the application used far more CPU than the Workers Free request budget and required a normal synchronous Python/PostgreSQL runtime.

Cloudflare Containers provide a standard Linux/Python environment for Django while retaining Cloudflare routing, R2, static assets and deployment.

## Supabase

Django authentication remains canonical; Supabase Auth is not used.

Django tables live in the private `django_app` schema with search path:

`django_app,extensions,public`

`pg_trgm` remains available for duplicate matching.

The deployment workflow:
1. validates the Direct Supabase URL;
2. derives the IPv4 Session Pooler URL automatically;
3. runs Django migrations against Supabase;
4. passes the Session Pooler URL to the container as an encrypted Worker secret.

## Cloudflare Container runtime

The container uses:
- `Dockerfile`
- `config.settings.container`
- Gunicorn on port 8080
- one `lite` container instance initially
- scale-to-zero after inactivity

The edge router is `src/container-worker.js`.

Preview Worker:
`canecorsoancestry-container-preview`

## Media

R2 remains private.

The container does not receive R2 access keys. `core.container_storage.CloudflareR2BridgeStorage` sends internal HTTP requests to the Worker, which accesses the native `MEDIA_BUCKET` R2 binding.

Public/private authorization remains in Django before media objects are served.

## Static assets

Django `collectstatic` builds static files. `scripts/build_cloudflare_assets.py` prepares `worker_assets/`, and Cloudflare serves `/static/*` directly at the edge before starting the container.

## Required GitHub secrets

Only these three are required:

- `CLOUDFLARE_API_TOKEN`
- `SUPABASE_DATABASE_URL`
- `DJANGO_SECRET_KEY`

No R2 access keys, Hyperdrive ID or separate pooler secret is required.

## Cloudflare prerequisites

The Cloudflare account must have **Workers Paid** enabled because Containers are not available on Workers Free.

The deployment API token must include:
- Account Settings: Read
- Workers: Admin for initial Worker creation
- Workers R2 Storage: Write
- **Containers: Write**
- Zone > Workers Routes: Write for `canecorsoancestry.com`

The workflow performs a Containers API preflight before migrations, Docker builds or deployment work.

## Deployment

Preview:
`wrangler.container.preview.jsonc`

Production:
`wrangler.container.production.jsonc`

Container deployments use:
`.github/workflows/cloudflare-container-deploy.yml`

Production remains an explicit manual target. The legacy Python Worker workflow is retained only as a manual diagnostic/rollback tool and must not auto-deploy from `main`.

## Cutover order

1. Keep the existing rollback source untouched.
2. Enable Workers Paid and ensure the API token has Containers Write.
3. Deploy the Cloudflare Container preview.
4. Verify `/healthz/`, login, admin, member dashboard, dog search, pedigrees, moderation and submissions.
5. Copy existing production media to R2 and verify object counts/hashes.
6. Verify Supabase production records/counts.
7. Deploy the production Container target.
8. Attach `canecorsoancestry.com` as the Cloudflare Custom Domain.
9. Repeat production smoke tests.
10. Remove the old environment only after the rollback window has passed.

## Security

- HTTPS-only production
- secure session and CSRF cookies
- private R2 media
- server-side media authorization
- Django tables outside Supabase `public`
- no Supabase service-role key in the application
- no R2 access keys in the container
- encrypted Worker secrets for database URL and Django secret
