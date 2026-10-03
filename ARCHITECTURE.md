# Architecture

## Active production stack

Cane Corso Ancestry is a server-rendered Django application with one public Cloudflare edge and one Django origin:

```
Browser
  |
  v
Cloudflare Workers site edge
canecorsoancestry-site-edge.aighewieghosa111.workers.dev
  |
  v
Northflank Django + Gunicorn + WhiteNoise
web--canecorsoancestry--4w9gl8jxj4yr.code.run
  |
  +----> Supabase PostgreSQL
  |
  +----> Cloudflare R2 media gateway ----> R2 bucket
```

No custom domain is currently configured.

## Cloudflare site edge

`src/site-edge.js` and `wrangler.site.toml` provide the public website endpoint.

The site edge:

- proxies requests to the Northflank Django origin;
- caches eligible public GET pages and static assets;
- keeps private/member/admin/media paths uncached;
- warms the origin and provides readiness endpoints for cold-start handling;
- rewrites origin redirects back to the public Workers hostname.

Public URL:

`https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`

## Northflank

Northflank runs Django and serves static files with WhiteNoise.

Current origin:

`https://web--canecorsoancestry--4w9gl8jxj4yr.code.run`

Production settings:

`config.settings.northflank`

The origin is intended to sit behind the Cloudflare site edge for normal public use.

## Supabase PostgreSQL

Supabase PostgreSQL is the canonical relational database.

GitHub and Northflank use the Supabase session-pooler connection derived from `SUPABASE_DATABASE_URL`.

Django uses schema:

`django_app`

Production search path includes:

`django_app,extensions,public`

Django authentication, sessions, moderation and application data live in this database.

## Cloudflare R2

R2 is the durable object store for uploaded media and evidence.

Media Worker:

`https://canecorsoancestry-edge.aighewieghosa111.workers.dev`

Supported media routes include:

- `/healthz/` — gateway health
- `/_r2/*` — authenticated backend R2 operations
- `/_media/*` — signed media delivery

Django authorizes media access before returning signed delivery URLs.

## Django applications

### `core`
Site shell, homepage, shared navigation, media authorization and dashboard.

### `accounts`
Member profile, member workspaces and moderation workflows.

### `registry`
Canonical dog, kennel, litter, image, health, source and external-registration records.

### `pedigrees`
Pedigree traversal, repeated-ancestor analysis, common-ancestor analysis, COI calculations and virtual mating.

## Active deployment files

- `Dockerfile`
- `config/settings/northflank.py`
- `src/site-edge.js`
- `src/r2-media.js`
- `wrangler.site.toml`
- `wrangler.r2.toml`
- `.github/workflows/provision-northflank.yml`
- `.github/workflows/cloudflare-site-edge.yml`
- `.github/workflows/cloudflare-media.yml`
- `.github/workflows/production-smoke.yml`

Maintenance data workflows connect to the same Supabase database and R2 storage.

## Scalability

For a growing pedigree catalog, concentrate on:

- PostgreSQL indexes and query plans;
- bounded pedigree traversal;
- pagination and selective search;
- conservative database connection counts;
- public edge caching;
- R2 object growth.
