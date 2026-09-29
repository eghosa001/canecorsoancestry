# Production Operations

Production compute is hosted on Railway. The current Railway PostgreSQL service and private bucket remain in place as rollback sources while the Supabase cutover is prepared.

## Supabase target

Supabase project ref: `wsntfvpcqloqzwgmsfaz` in `eu-north-1`.

The target is deliberately split as follows:

- Django authentication remains the application's canonical authentication system.
- Django tables live in the non-exposed `django_app` PostgreSQL schema.
- `extensions` remains on the database search path so `pg_trgm` works for duplicate matching.
- Supabase Storage uses the private `ancestry-private` bucket through its server-side S3-compatible endpoint.
- Supabase Auth is not used, avoiding a second user identity system and preserving current Django permissions, admin, moderation and sessions.

The one-time Supabase bootstrap is stored in `scripts/supabase_bootstrap.sql`.

## Deployment

- Source: GitHub `eghosa001/canecorsoancestry`, branch `main`.
- Build: collect static assets.
- Pre-deploy: run Django migrations.
- Runtime: Gunicorn.
- Health: `/healthz/`.
- Project-level desired state: `.railway/railway.ts` (Railway Infrastructure as Code).

## Required variables

Core production variables:

`DJANGO_SETTINGS_MODULE=config.settings.production`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DATABASE_URL`, `DJANGO_REQUIRE_OBJECT_STORAGE=1`.

For Supabase database cutover:

- `DATABASE_URL`: use the Supabase **Session pooler** connection string from the project's Connect panel. Railway should use the IPv4-compatible session pooler rather than the direct IPv6-only database endpoint.
- `DJANGO_DB_SCHEMA=django_app`
- `DJANGO_DB_SSLMODE=require`

For Supabase Storage:

- `SUPABASE_PROJECT_REF=wsntfvpcqloqzwgmsfaz`
- `SUPABASE_REGION=eu-north-1`
- `SUPABASE_STORAGE_BUCKET=ancestry-private`
- `SUPABASE_S3_ENDPOINT_URL=https://wsntfvpcqloqzwgmsfaz.storage.supabase.co/storage/v1/s3`
- `SUPABASE_S3_ACCESS_KEY_ID`
- `SUPABASE_S3_SECRET_ACCESS_KEY`

S3 access keys are server-side secrets and must never be committed. Generate them in Supabase Storage > S3 Configuration. Generic `BUCKET`, `REGION`, `ENDPOINT`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` variables remain supported for rollback and non-Supabase S3 providers.

## Cutover sequence

1. Keep Railway PostgreSQL and Railway object storage unchanged.
2. Bootstrap the Supabase private schema/storage using `scripts/supabase_bootstrap.sql`.
3. Generate the Supabase database password / Session pooler connection string and S3 access keys in the Supabase dashboard.
4. Copy the existing production database and media into Supabase.
5. Set the Supabase production variables on the Railway web service.
6. Run `python manage.py migrate --noinput`, `python manage.py check`, the focused production tests, and a storage read/write/delete probe.
7. Verify `/healthz/`, login, moderation, public dog pages, pedigree traversal, search, uploads and signed downloads.
8. Keep the old Railway database/bucket available until the Supabase production deployment is verified and a rollback window has passed.

Do not point production at the empty Supabase database before the data copy is complete.

## Media

The production bucket is private. Approved media/document URLs are time-limited signed S3 URLs. Evidence is never placed in a public bucket.

Supabase Storage S3 access keys are full server-side credentials and bypass Storage RLS; they must stay only in the Railway secret store. The bucket itself remains private.

## Email

The selected transactional provider is Resend SMTP (`smtp.resend.com:587`, user `resend`). Keep `ANCESTRY_EMAIL_NOTIFICATIONS=0` until the Resend API key and sender-domain verification are present, then store the key only as `EMAIL_HOST_PASSWORD`. Never commit that credential.

## Monitoring

Railway provides deploy/runtime/proxy logs and the health check. Every response gets an `X-Request-ID`. Optional Sentry support is enabled by setting `SENTRY_DSN`; no PII is sent by default.

## Backups

Until the Supabase cutover is verified, retain the existing Railway PostgreSQL backup schedule and do not remove the Railway database volume.

After cutover, configure and verify Supabase backups appropriate to the project plan, and perform a restore test before removing the Railway database rollback copy.

## SEO

Public surfaces expose `/robots.txt`, `/sitemap.xml`, canonical/Open Graph metadata, WebSite SearchAction JSON-LD and public dog JSON-LD. Member/login/admin/dashboard surfaces emit noindex headers and private/no-store caching.

## Security

HTTPS redirect, secure cookies, proxy-aware HTTPS detection, CSRF trusted origins, staged HSTS, no framing, MIME sniff protection, same-origin referrer/COOP policy, restrictive permissions policy, private object storage and server-side authorization checks.

Django tables are intentionally placed in `django_app`, not Supabase's exposed `public` schema. Access for `anon` and `authenticated` is revoked at the schema/default-privilege level. Django connects server-side using PostgreSQL credentials.

Start HSTS at one hour. After the custom domain and all subdomains are stable on HTTPS, raise `DJANGO_HSTS_SECONDS` to `31536000`; enable preload only after confirming every subdomain is HTTPS-only.

## Production seed

The first production import completed successfully: 117 canonical Bellissimo-source dogs were created, including 101 public records and 16 drafts. Subsequent imports reuse external keys and do not create duplicate canonical dogs.

## Domain

Railway custom domain: `canecorsoancestry.com`.

Required DNS record:

- type: CNAME
- name: `canecorsoancestry.com`
- target: `7i4x0mqk.up.railway.app`

The current Railway plan permits one custom domain on this service. Configure `www.canecorsoancestry.com` as a DNS/CDN redirect to the apex rather than attaching it separately to Railway.
