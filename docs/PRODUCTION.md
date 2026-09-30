# Production Operations

## Final production architecture

Cane Corso Ancestry is moving to **Cloudflare + Supabase**.

- Application runtime: Cloudflare Python Workers
- WSGI adapter: Cloudflare Workers Python WSGI support
- Database: Supabase PostgreSQL project `wsntfvpcqloqzwgmsfaz` (`eu-north-1`)
- Database connection pooling: Cloudflare Hyperdrive
- Media/evidence: private Cloudflare R2 bucket `canecorsoancestry-media`
- Static assets: Cloudflare Workers Static Assets
- DNS/TLS/application origin: Cloudflare Custom Domain on `canecorsoancestry.com`

Railway remains only as a temporary rollback/source environment until the cutover is verified.

## Supabase database

Django authentication remains canonical; Supabase Auth is not used.

Django tables live in the non-exposed `django_app` schema.

The target search path is:

`django_app,extensions,public`

`pg_trgm` remains available from the `extensions` schema for duplicate matching.

The Supabase security advisor should remain clean after schema changes.

## Cloudflare runtime

Cloudflare runs `worker.py`, which loads:

`DJANGO_SETTINGS_MODULE=config.settings.cloudflare`

The Worker requires these bindings:

- `HYPERDRIVE` — points to Supabase PostgreSQL
- `MEDIA_BUCKET` — R2 bucket `canecorsoancestry-media`
- `ASSETS` — Workers Static Assets bundle

The only mandatory Worker secret used by Django itself is:

- `DJANGO_SECRET_KEY`

Do not commit it.

## Static assets

Before deployment:

1. Run Django `collectstatic`.
2. Run `python scripts/build_cloudflare_assets.py`.
3. Deploy the generated `worker_assets/` directory with the Worker.

`/static/*` is served directly by Cloudflare's asset layer, while application routes invoke Django.

## Media

Production uploads use `core.storage.CloudflareR2Storage`.

The storage backend uses the native R2 Worker binding, not S3 credentials. That avoids carrying Railway bucket credentials or synchronous boto3 networking into Python Workers.

Media URLs resolve through Django's `/media/<path>` route. Django authorizes each request before reading the R2 object.

Public access is intentionally narrow:
- public-dog images;
- explicitly public documents attached to public dogs.

Private submissions, dispute evidence, source documents and private member documents require an authorized user or staff account.

## Deployment configs

`wrangler.preview.toml` deploys to workers.dev for verification.

`wrangler.production.toml` adds:

`canecorsoancestry.com`

as a Cloudflare Custom Domain.

Both files keep the Hyperdrive ID as a placeholder. The deployment pipeline creates or updates the cache-disabled `canecorsoancestry-supabase` Hyperdrive from the Direct Supabase database URL, discovers its ID through the Cloudflare API, and renders the temporary `wrangler.toml` without committing credentials or resource IDs.

## GitHub deployment secrets

The Cloudflare deploy workflow requires only these GitHub Actions secrets:

- `CLOUDFLARE_API_TOKEN`
- `SUPABASE_DATABASE_URL` — the **Direct** Supabase PostgreSQL connection string
- `DJANGO_SECRET_KEY`

The workflow discovers the Cloudflare account ID from the token automatically. If the token can access more than one Cloudflare account, set the optional repository variable `CLOUDFLARE_ACCOUNT_ID` to select the correct one.

Those values belong in GitHub Actions secrets, never in the repository. The workflow automatically creates or updates a cache-disabled Hyperdrive configuration named `canecorsoancestry-supabase`, so no Hyperdrive ID needs to be entered manually.

## Database migration

The existing `copy_to_supabase` management command is the controlled database migration path.

Run it from the existing Railway application while Railway's PostgreSQL database is still the default source and `SUPABASE_DATABASE_URL` points to the Supabase target.

The command:

1. applies Django migrations to the Supabase target;
2. copies Django users/groups, active database sessions, Django admin log entries, accounts and registry data;
3. verifies source/target model counts, including sessions and admin audit history;
4. refuses to overwrite an already populated target unless `--replace` is explicitly supplied.

Use the same `DJANGO_SECRET_KEY` on Cloudflare as Railway so copied database sessions remain valid after cutover.

Do not change production traffic to Supabase until that verification succeeds.

## Cutover order

1. Keep Railway fully intact.
2. Configure the Supabase database connection for migration.
3. Run and verify `copy_to_supabase`.
4. Run the Cloudflare preview deploy workflow; it creates or updates the cache-disabled Hyperdrive against the validated Supabase Direct connection automatically.
5. The same workflow creates/verifies the `canecorsoancestry-media` R2 bucket.
6. Verify the deployed **preview** Worker.
7. Verify `/healthz/`, login, admin, member dashboard, search, dog profiles, pedigrees, duplicate matching, moderation, submissions, uploads and private/public media access.
8. Copy existing production media from the Railway bucket to R2 using:
   `python manage.py copy_media_to_cloudflare --target-url=https://<preview>.workers.dev`.
   The preview-only importer accepts only database-referenced paths and HMAC-signed bytes, verifies SHA-256, and is disabled in the production Worker config.
9. Re-run the command until every referenced media object reports stored or already identical. Any missing source object is a blocking error.
10. Remove the old apex CNAME that points to Railway.
11. Deploy using the **production** target so Cloudflare creates the Custom Domain for `canecorsoancestry.com`. The production Worker has `MEDIA_MIGRATION_ENABLED=0`.
12. Repeat production smoke tests.
13. Keep Railway available during the rollback window.
14. Remove Railway only after the new stack is confirmed stable.

## Domain

Cloudflare Custom Domains are the final origin configuration.

The old Railway CNAME for `canecorsoancestry.com` must be removed before Cloudflare can attach the same hostname as a Custom Domain.

`www.canecorsoancestry.com` should redirect to the apex unless a second Custom Domain is intentionally configured.

## Email

In-app notifications continue to work.

SMTP mail is disabled in the Cloudflare Worker settings for the initial cutover because the old Railway SMTP path is not required for correctness and should not block the migration. Transactional email can be reintroduced using a Worker-compatible HTTP email provider after the runtime cutover.

## Backups and rollback

Do not remove the Railway PostgreSQL volume or its backups during migration.

After Supabase becomes canonical, enable/verify the Supabase backup policy appropriate to the project plan and perform a restore test before deleting the Railway rollback copy.

R2 media should also have an export/backup procedure before the Railway bucket is deleted.

## Security

- HTTPS-only production
- secure session and CSRF cookies
- HSTS staged initially at one hour
- no framing
- MIME-sniff protection
- same-origin referrer/COOP policy
- private R2 media by default
- server-side media authorization
- Django tables outside Supabase `public`
- no Supabase service-role key in the Worker
- no R2 access keys in the Worker; the native binding supplies capability access

After all production hostnames are stable on HTTPS, HSTS may be raised to one year and preload considered.

## Production seed

The current source production database previously imported 117 canonical Bellissimo-source dogs, including 101 public records and 16 drafts. The data copy must preserve those canonical IDs and all later member/moderation records rather than re-seeding production from scratch.


## Media migration authentication

The preview media importer signs each request with Django's existing `DJANGO_SECRET_KEY`. For the cutover, configure the Cloudflare Worker with the **same Django secret currently used by Railway**. This preserves existing Django signing behavior and lets the Railway source authenticate the one-time R2 copy without introducing another migration secret.

Do not paste the secret into logs, repository files, command arguments, or chat. Store the same value in the GitHub Actions `DJANGO_SECRET_KEY` secret.

The importer is enabled only in `wrangler.preview.toml`; `wrangler.production.toml` disables it.
