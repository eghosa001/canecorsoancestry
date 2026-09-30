# Architecture

## Stack

Cane Corso Ancestry is a server-rendered Django application.

Primary production stack:

- Django 5.2 / Python 3.13 on Render
- Gunicorn with one worker and two threads on the free Render instance
- Cloudflare Worker as the public edge/router
- Cloudflare Workers Static Assets for CSS/static files
- Cloudflare R2 for uploaded media and evidence
- Aiven PostgreSQL as the canonical production database
- GitHub Actions for CI, database migration and edge deployment

Supabase is retained only as the source for the one-time migration to Aiven. Google Cloud Run and Railway are not part of the active production architecture.

## Django applications

### `core`
Site shell, homepage, shared navigation, media authorization and member dashboard.

### `accounts`
Member profile and account-specific features.

### `registry`
Canonical dog, kennel, litter, image, health, source and external-registration records.

### `pedigrees`
Pedigree traversal, repeated-ancestor analysis, common-ancestor analysis, COI calculations and virtual mating.

## Database

Aiven PostgreSQL is the production target.

Django tables live in the private application schema:

`django_app`

The Aiven production search path is:

`django_app,public`

The temporary Supabase migration source continues to use `django_app,extensions,public` until cutover. `pg_trgm` supports duplicate and fuzzy matching; on Aiven it is installed in a supported schema reachable through `public`.

Django authentication remains authoritative. No provider-specific database authentication layer is required.

The Aiven free tier has a small connection limit, so the Render service intentionally uses one Gunicorn worker with two threads and Django connection reuse rather than a large worker pool.

## Render runtime

`render.yaml` defines the free Python web service.

`config.settings.render` extends the hardened production settings, uses the signed Cloudflare R2 gateway for media storage and can enable the Cloudflare origin gate.

Render's filesystem is ephemeral, so no durable application data or uploads are stored locally.

`/healthz/` remains directly reachable so Render can perform health checks even when the rest of the origin is edge-gated.

## Cloudflare edge

`src/edge.js` is the public edge Worker.

It:

- serves collected static assets at the edge;
- proxies dynamic requests to the Render origin;
- adds a signed edge-auth header to proxied application requests;
- owns the native R2 binding;
- validates HMAC-signed backend storage requests;
- validates short-lived signed media-delivery URLs;
- redirects `www.canecorsoancestry.com` to the apex domain.

The preview Worker and production Worker use different names so CI/push deployments cannot overwrite production custom-domain routes.

## Media

Django stores R2 object keys in existing FileField columns.

For uploads and storage metadata operations, Render uses:

`core.r2_gateway_storage.CloudflareR2GatewayStorage`

It signs requests to the Cloudflare `/_r2/*` gateway using `DJANGO_SECRET_KEY`.

For downloads, Django authorizes the user and redirects to a short-lived `/_media/*` URL. Cloudflare then streams the R2 object directly.

## Static assets

Django `collectstatic` produces static files. The Cloudflare edge build copies them into `worker_assets/static/`, and Workers Static Assets serves `/static/*` without invoking Render.

## Authentication and authorization

Django sessions, users, permissions and admin remain authoritative.

Expected application roles include member, kennel contributor/editor/owner and moderator/admin.

## Deployment

CI validates:

- Django migrations, checks and tests;
- Render production settings;
- Cloudflare Worker JavaScript;
- preview and production Wrangler bundles;
- responsive browser smoke tests.

The main deployment files are:

- `render.yaml`
- `.github/workflows/render-edge-build.yml`
- `.github/workflows/cloudflare-media.yml`
- `.github/workflows/aiven-migrate.yml`
- `.github/workflows/production-seed.yml`
- `.github/workflows/sync-bellissimo-media.yml`

Aiven migration is deliberately manual and refuses a target that already contains the `django_app` schema.

## Scalability

The app tier is stateless. R2 owns large binary media and Aiven owns relational state.

For a catalog approaching 100,000 dogs, performance work should focus on:

- database size and the free-tier storage ceiling;
- query plans and indexes;
- bounded pedigree traversal;
- pagination and search selectivity;
- keeping database connection counts below the Aiven plan limit;
- cacheable public pages and media.

If the dataset outgrows the free database plan, the application remains portable because Django connects through the standard `DATABASE_URL` setting.

## Rollback

Before cutover, Supabase remains the source of truth.

After the verified Aiven copy:

1. update Render to use Aiven;
2. verify the site and writes on Aiven;
3. keep Supabase temporarily as a read-only snapshot;
4. remove Supabase credentials only after the new stack is confirmed stable.

Cloudflare edge deployments and Render application deployments can be rolled back independently.
