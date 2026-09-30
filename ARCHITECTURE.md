# Architecture

## Stack

Cane Corso Ancestry is a server-rendered Django application.

Primary production stack:

- Django 5.2 / Python 3.13 on Google Cloud Run
- Gunicorn inside the Cloud Run container
- Cloudflare Worker as the public edge/router
- Cloudflare Workers Static Assets for CSS/static files
- Cloudflare R2 for uploaded media and evidence
- Supabase PostgreSQL as the canonical database
- Supabase Session Pooler for Cloud Run database connectivity
- GitHub Actions for CI and deployment

The final runtime does not depend on Railway or Cloudflare Containers.

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

Supabase PostgreSQL is canonical.

Django tables live in the private `django_app` schema. The search path is:

`django_app,extensions,public`

`pg_trgm` supports duplicate matching.

Django authentication remains authoritative; Supabase Auth is intentionally not introduced.

## Cloud Run runtime

`Dockerfile` builds a normal CPython/Gunicorn image.

`config.settings.cloudrun` extends the hardened production settings and replaces media storage with the signed Cloudflare R2 gateway backend.

Cloud Run starts at zero instances and scales up within an explicit maximum-instance cap.

## Cloudflare edge

`src/cloudrun-edge.js` is intentionally lightweight.

It:

- serves static assets at the edge;
- proxies dynamic requests to Cloud Run;
- owns the native R2 binding;
- validates HMAC-signed backend storage requests;
- validates short-lived signed media-delivery URLs.

The edge Worker does not run Django.

## Media

Django stores R2 object keys in existing FileField columns.

For uploads and storage metadata operations, Cloud Run uses:

`core.cloudrun_storage.CloudflareR2GatewayStorage`

The backend signs requests to the Cloudflare `/_r2/*` gateway using `DJANGO_SECRET_KEY`.

For downloads, Django authorizes the user and redirects to a short-lived `/_media/*` signature. Cloudflare then streams the R2 object directly.

This keeps private-access decisions server-side without routing image bytes through Cloud Run.

## Static assets

Django `collectstatic` produces static files. The deployment pipeline copies them into `worker_assets/static/`, and Workers Static Assets serves `/static/*` without invoking Cloud Run.

## Authentication and authorization

Django sessions, users, permissions and admin remain authoritative.

Expected application roles include member, kennel contributor/editor/owner and moderator/admin.

## Pedigree analysis

The database-backed analysis layer remains deterministic:

- bounded pedigree traversal;
- repeated ancestor detection;
- sibling discovery;
- offspring queries;
- common ancestors;
- COI;
- virtual mating.

## Deployment

CI validates:

- Django tests and deploy checks;
- the Cloud Run Docker image;
- Cloud Run settings;
- Cloudflare Worker JavaScript;
- Cloudflare edge dry-run bundle.

Production deployment uses:

`.github/workflows/cloudrun-deploy.yml`

GitHub authenticates to Google using Workload Identity Federation. Sensitive application values are stored in Google Secret Manager and pinned to Cloud Run revisions.

## Scalability

The app tier is stateless. Cloud Run can add instances without migrating application state.

Supabase owns relational state and indexes. R2 owns large binary media.

For a future catalog approaching 100,000 dogs, performance work should focus on:

- database indexes and query plans;
- bounded pedigree traversal;
- pagination/search selectivity;
- connection-pool sizing;
- cacheable public pages/media;
- database capacity before application-compute capacity.

## Rollback

Cloud Run revisions and container images provide application rollback.

Supabase migrations and backups cover database rollback.

Cloudflare edge deployments can be rolled back independently of the Django image.
