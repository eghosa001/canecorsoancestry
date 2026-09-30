# Production Operations

## Final production architecture

Cane Corso Ancestry uses **Cloudflare + Supabase**.

- Application runtime: Cloudflare Containers running Django/Gunicorn
- Edge router/static assets: Cloudflare Workers + Workers Static Assets
- Database: Supabase PostgreSQL project `wsntfvpcqloqzwgmsfaz` in `eu-north-1`
- Database connectivity: Supabase Session Pooler from the container
- Media/evidence: private Cloudflare R2 bucket `canecorsoancestry-media`
- DNS/TLS/application origin: Cloudflare Custom Domain on `canecorsoancestry.com`

Railway is not part of the final architecture. It remains only as a temporary rollback/source environment until data/media cutover is verified.

## Why Containers instead of Python Workers

The Django application was tested on Cloudflare Python Workers. The Worker package and bindings deployed correctly, but the application consistently used far more CPU than the Workers Free 10 ms request limit and also required a normal synchronous Python/PostgreSQL runtime.

Cloudflare Containers provide a normal Linux/Python runtime for Django while retaining Cloudflare routing, R2, scaling and deployment.

## Supabase

Django authentication remains canonical; Supabase Auth is not used.

Django tables live in the private `django_app` schema with search path:

`django_app,extensions,public`

`pg_trgm` is available for duplicate matching.

The deploy workflow:
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

The Worker router is `src/container-worker.js`.

The preview Worker is `canecorsoancestry-container-preview`.

## Media

R2 remains private.

The container does not receive R2 access keys. Instead, `core.container_storage.CloudflareR2BridgeStorage` sends internal HTTP requests to the Worker. The Worker resolves those requests through the native `MEDIA_BUCKET` R2 binding.

Public/private authorization remains in Django's existing `/media/<path>` route.

## Static assets

Django `collectstatic` builds the files. `scripts/build_cloudflare_assets.py` prepares `worker_assets/`, and Cloudflare serves `/static/*` directly at the edge before requests reach the container.

## Required GitHub secrets

Only these three are required:

- `CLOUDFLARE_API_TOKEN`
- `SUPABASE_DATABASE_URL`
- `DJANGO_SECRET_KEY`

No R2 access keys, Hyperdrive ID or separate pooler secret is required.

## Cloudflare API token permissions

For the Container deployment token, grant:

- Account Settings: Read
- Workers: Admin for first Worker creation
- Workers R2 Storage: Write
- **Containers: Write**
- Zone > Workers Routes: Write for `canecorsoancestry.com`

The account must also be on **Workers Paid**, because Cloudflare Containers are not available on Workers Free.

## Deployment

Preview config:
`wrangler.container.preview.jsonc`

Production config:
`wrangler.container.production.jsonc`

Preview deploys automatically from `main` when Container runtime files change. Production remains manual through `.github/workflows/cloudflare-container-deploy.yml`.

The legacy Python Worker deploy workflow is manual-only and should not be used for production.

## Cutover order

1. Keep the existing rollback source untouched.
2. Ensure Supabase migrations are current.
3. Deploy the Cloudflare Container preview.
4. Verify `/healthz/`, login, admin, member dashboard, dog search, pedigrees, moderation and submissions.
5. Copy existing production media into R2 and verify object counts/hashes.
6. Deploy the production Container target.
7. Attach `canecorsoancestry.com` as the Cloudflare Custom Domain.
8. Repeat production smoke tests.
9. Retain the old environment only for the rollback window.
10. Remove the old environment after the new stack is stable.

## Security

- HTTPS-only production
- secure session and CSRF cookies
- private R2 media
- server-side media authorization
- Django tables outside Supabase `public`
- no Supabase service-role key in the application
- no R2 access keys in the container
- encrypted Worker secrets for database URL and Django secret
