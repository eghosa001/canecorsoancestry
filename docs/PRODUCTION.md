# Production Operations

Production is hosted on Railway with a Django web service, private PostgreSQL service and private S3-compatible storage bucket.

## Deployment
- Build: collect static assets.
- Pre-deploy: run Django migrations.
- Runtime: Gunicorn.
- Health: `/healthz/`.
- Configuration: `railway.toml`.

## Required variables
`DJANGO_SETTINGS_MODULE=config.settings.production`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DATABASE_URL`, `DJANGO_REQUIRE_OBJECT_STORAGE=1`, `BUCKET`, `REGION`, `ENDPOINT`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.

Use Railway resource references instead of copying database or bucket secrets.

## Media
The production bucket is private. Approved media/document URLs are time-limited signed S3 URLs. Evidence is never placed in a public bucket.

## Email
The selected transactional provider is Resend SMTP (`smtp.resend.com:587`, user `resend`). Keep `ANCESTRY_EMAIL_NOTIFICATIONS=0` until the Resend API key and sender-domain verification are present, then store the key only as `EMAIL_HOST_PASSWORD`.

## Monitoring
Railway provides deploy/runtime/proxy logs and the health check. Every response gets an `X-Request-ID`. Optional Sentry support is enabled by setting `SENTRY_DSN`; no PII is sent by default.

## Backups
Configure Railway native volume backups on PostgreSQL:
- Daily: retained 6 days.
- Weekly: retained 27 days.
- Monthly: retained 89 days.
Test a restore before relying on the backup policy.

## SEO
Public surfaces expose `/robots.txt`, `/sitemap.xml`, canonical/Open Graph metadata, WebSite SearchAction JSON-LD and public dog JSON-LD. Member/login/admin/dashboard surfaces emit noindex headers and private/no-store caching.

## Security
HTTPS redirect, secure cookies, proxy-aware HTTPS detection, CSRF trusted origins, staged HSTS, no framing, MIME sniff protection, same-origin referrer/COOP policy, restrictive permissions policy, private object storage and server-side authorization checks.

Start HSTS at one hour. After the custom domain and all subdomains are stable on HTTPS, raise `DJANGO_HSTS_SECONDS` to `31536000`; enable preload only after confirming every subdomain is HTTPS-only.
