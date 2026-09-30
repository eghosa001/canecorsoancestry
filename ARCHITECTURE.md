# Architecture

## Stack

Cane Corso Ancestry is a server-rendered Django application.

Primary production stack:

- Python 3.13 on Cloudflare Python Workers
- Django 5.2 via the Cloudflare WSGI adapter
- Supabase PostgreSQL as the canonical database
- Cloudflare Hyperdrive between Workers and Supabase PostgreSQL
- Cloudflare R2 for uploaded dog images, evidence and documents
- Cloudflare Workers Static Assets for CSS and other static files
- Django templates for server-rendered pages
- GitHub Actions for CI and controlled Cloudflare deployments

The public experience remains usable without a heavy JavaScript application shell.

## Current Django apps

### `core`

Site shell, homepage, shared navigation, media authorization and the custom member dashboard.

### `accounts`

Member profile and account-specific features.

### `registry`

Internal code package for canonical dog, kennel, litter, image, health, source and external-registration records.

The package name is internal only. **The public product must not be presented as a registry.**

### `pedigrees`

Pedigree traversal, repeated-ancestor analysis, common-ancestor analysis, COI calculations and virtual mating.

## Core record graph

`Dog` is the canonical node.

Each dog can reference:
- one sire;
- one dam;
- one kennel;
- one litter;
- aliases;
- external registrations;
- images;
- health records;
- evidence/sources.

Repeated appearances of one ancestor in a rendered pedigree do not create extra Dog rows.

## Database

Supabase PostgreSQL is the canonical production database.

Django tables live in the private `django_app` schema rather than Supabase's exposed `public` schema. The connection search path is:

`django_app,extensions,public`

This preserves access to PostgreSQL extensions such as `pg_trgm` without exposing Django's tables through the Supabase Data API.

Cloudflare Workers connect through the `HYPERDRIVE` binding. Hyperdrive owns connection pooling, so Django uses short-lived application connections (`CONN_MAX_AGE=0`).

Use constraints for facts that must be unique or singular, including:
- one kennel membership per user/kennel pair;
- one external registration number per authority;
- one primary image per dog;
- unique canonical slugs.

Pedigree code must be cycle-safe. A malformed ancestry cycle must not recurse forever.

## Media

Uploaded media is stored in the private Cloudflare R2 bucket bound as `MEDIA_BUCKET`.

Django keeps the object key in its existing FileField columns. `core.storage.CloudflareR2Storage` bridges Django's synchronous Storage API to the asynchronous R2 binding using Pyodide's `run_sync` bridge.

All media access goes through `/media/<path>`, where Django authorizes the request before the object is opened:

- dog images for public dogs may be served publicly;
- documents are public only when both the document and dog are public;
- member submissions, dispute evidence and private documents require membership/ownership or staff authorization.

Evidence is never exposed merely because somebody knows the R2 key.

Original uploaded media remains the source of truth. Do not repeatedly recompress dog photography, and preserve natural framing.

## Static assets

Django `collectstatic` builds the project static files. The deploy pipeline copies them into `worker_assets/static/`, and Cloudflare Workers Static Assets serves `/static/*` directly without invoking Django.

## Authentication and authorization

Django authentication remains canonical. Supabase Auth is intentionally not introduced because that would create a second identity system and break existing Django sessions, staff permissions and moderation workflows.

Normal breeders/members receive the custom member dashboard. Django Admin is for internal moderation/operations.

Expected roles:

- member;
- kennel contributor;
- kennel editor;
- kennel owner;
- moderator/admin.

Permissions are enforced server-side.

## Verification

Verification is evidence-scoped.

Progression:

1. Community submitted
2. Source attached
3. Identity reviewed
4. Pedigree reviewed
5. Health/DNA verified

A kennel has a separate verification state.

## Pedigree analysis

The analysis layer provides deterministic services independent from templates:

- bounded pedigree traversal;
- repeated ancestor detection;
- full/half sibling discovery;
- offspring queries;
- common ancestor detection;
- inbreeding coefficient calculations;
- projected virtual-mating coefficient.

Calculation code uses short unit tests with small known pedigrees.

## Cloudflare deployment

`worker.py` is the Cloudflare WSGI entrypoint.

`config.settings.cloudflare` is isolated from the existing Railway settings so rollback remains possible during migration.

The repository contains:

- `wrangler.preview.toml` for workers.dev verification;
- `wrangler.production.toml` for the final `canecorsoancestry.com` Custom Domain;
- `scripts/render_wrangler.py` to inject the Hyperdrive binding ID without committing it;
- `scripts/build_cloudflare_assets.py` to prepare Workers Static Assets;
- `.github/workflows/cloudflare-build.yml` for bundle dry-run validation;
- `.github/workflows/cloudflare-deploy.yml` for controlled preview/production deployment.

## Migration and rollback

Railway is no longer the target architecture. It remains temporarily as the source and rollback copy until Cloudflare + Supabase passes production verification.

Do not remove the Railway web service, PostgreSQL volume or bucket until:

1. the production database has been copied and verified in Supabase;
2. required existing media has been copied to R2;
3. the Worker preview passes health, login, search, pedigree, moderation and upload/download tests;
4. `canecorsoancestry.com` is serving the verified Worker deployment;
5. a rollback window has passed.

After those conditions are satisfied, Railway can be retired.

## CI philosophy

Keep CI focused and fast:

- migration drift check;
- `manage.py check`;
- short Django unit tests;
- Cloudflare Worker bundle dry run for runtime/config changes;
- small responsive browser smoke coverage.

Do not run expensive unrelated suites for narrow changes.
