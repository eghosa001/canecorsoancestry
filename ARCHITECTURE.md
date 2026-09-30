# Architecture

## Stack

Cane Corso Ancestry is a server-rendered Django application.

Primary production stack:

- Django 5.2 / Python 3.13 in Cloudflare Containers
- Gunicorn inside the container
- Cloudflare Worker as the edge router
- Cloudflare Workers Static Assets for CSS/static files
- Supabase PostgreSQL as the canonical database
- Supabase Session Pooler for container database connectivity
- Cloudflare R2 for uploaded dog images, evidence and documents
- GitHub Actions for CI and Cloudflare deployment

The final runtime does not depend on Railway.

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

Django authentication remains canonical; Supabase Auth is intentionally not introduced.

## Container runtime

`Dockerfile` creates the Django image.

`src/container-worker.js` defines the Cloudflare Container class and routes incoming requests to one named application container.

The initial instance type is `lite`, with one concurrent instance and scale-to-zero after inactivity.

Secrets are passed from encrypted Worker bindings into the container environment.

## Media

R2 is bound to the Worker as `MEDIA_BUCKET`.

The container accesses R2 through an internal outbound bridge at `r2.internal`; it never receives R2 credentials.

Django stores only object keys in existing FileField columns. `core.container_storage.CloudflareR2BridgeStorage` implements save/open/head/delete against that private bridge.

All public/private access remains authorized by Django before objects are served.

## Static assets

Django `collectstatic` produces static files. The deployment pipeline copies them into `worker_assets/static/`, and Cloudflare Workers Static Assets serves `/static/*` without starting the container.

## Authentication and authorization

Django sessions, users, permissions and admin remain authoritative.

Expected application roles include member, kennel contributor/editor/owner and moderator/admin.

## Pedigree analysis

The analysis layer remains deterministic and database-backed:
- bounded traversal;
- repeated ancestor detection;
- sibling discovery;
- offspring queries;
- common ancestors;
- COI;
- virtual mating.

## Deployment

Preview:
`wrangler.container.preview.jsonc`

Production:
`wrangler.container.production.jsonc`

CI validates:
- Django checks/tests;
- Docker image build;
- Wrangler Container configuration.

The deployment workflow applies Supabase migrations, prepares static assets, sets encrypted Worker secrets and deploys the Cloudflare Container.

## Rollback

The previous environment remains only until:
1. Supabase data is verified;
2. R2 media is verified;
3. Container preview passes application smoke tests;
4. the custom domain serves the Container deployment;
5. the rollback window has passed.

After that, the previous environment is removed.
