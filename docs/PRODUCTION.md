# Production Operations

Production is hosted on Railway with a Django web service, private PostgreSQL service and private S3-compatible storage bucket. The web service is live and Railway's health probe returns HTTP 200.

## Deployment
- Source: GitHub `eghosa001/canecorsoancestry`, branch `main`.
- Build: collect static assets.
- Pre-deploy: run Django migrations.
- Runtime: Gunicorn.
- Health: `/healthz/`.
- Project-level desired state: `.railway/railway.ts` (Railway Infrastructure as Code).

## Required variables
`DJANGO_SETTINGS_MODULE=config.settings.production`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DATABASE_URL`, `DJANGO_REQUIRE_OBJECT_STORAGE=1`, `BUCKET`, `REGION`, `ENDPOINT`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.

Use Railway resource references instead of copying database or bucket secrets.

## Media
The production bucket is private. Approved media/document URLs are time-limited signed S3 URLs. Evidence is never placed in a public bucket.

Live verification completed through Django `default_storage`: a temporary `healthchecks/storage-probe.txt` object was PUT, read back with matching contents, and deleted successfully.

## Email
The selected transactional provider is Resend SMTP (`smtp.resend.com:587`, user `resend`). Keep `ANCESTRY_EMAIL_NOTIFICATIONS=0` until the Resend API key and sender-domain verification are present, then store the key only as `EMAIL_HOST_PASSWORD`. Never commit that credential.

## Monitoring
Railway provides deploy/runtime/proxy logs and the health check. Every response gets an `X-Request-ID`. Optional Sentry support is enabled by setting `SENTRY_DSN`; no PII is sent by default.

## Backups
Daily / Weekly / Monthly schedules were submitted for the PostgreSQL volume. Railway's current API does not return backup schedule state, so operational verification must use the Railway Backups tab or `railway postgres pitr schedule list`.

Expected retention:
- Daily: retained 6 days.
- Weekly: retained 27 days.
- Monthly: retained 89 days.

Test a restore before relying on the backup policy.

## SEO
Public surfaces expose `/robots.txt`, `/sitemap.xml`, canonical/Open Graph metadata, WebSite SearchAction JSON-LD and public dog JSON-LD. Member/login/admin/dashboard surfaces emit noindex headers and private/no-store caching.

## Security
HTTPS redirect, secure cookies, proxy-aware HTTPS detection, CSRF trusted origins, staged HSTS, no framing, MIME sniff protection, same-origin referrer/COOP policy, restrictive permissions policy, private object storage and server-side authorization checks.

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
