# Production Operations

## Final production architecture

Cane Corso Ancestry uses **Cloudflare + Google Cloud Run + Supabase**.

- **Cloudflare Worker**: public edge proxy, custom domain routing, static assets and private R2 gateway.
- **Cloudflare R2**: dog photographs, evidence and uploaded documents.
- **Google Cloud Run**: Django 5.2 + Gunicorn application runtime.
- **Supabase PostgreSQL**: canonical application database.
- **GitHub Actions**: migrations, image build/push and controlled preview/production deployment.

Railway and Cloudflare Containers are not part of the final runtime.

## Regions and scaling

Cloud Run defaults to `europe-north1` (Finland), close to the Supabase project in `eu-north-1`.

Initial Cloud Run limits are deliberately conservative:

- 1 vCPU
- 512 MiB memory
- minimum instances: 0
- maximum instances: 3
- concurrency: 40
- 60 second request timeout

This preserves scale-to-zero behavior and caps unexpected compute growth while the service is small.

## Supabase

Django authentication remains canonical; Supabase Auth is not used.

Django tables live in the private `django_app` schema with search path:

`django_app,extensions,public`

The deploy workflow:

1. validates the existing Direct Supabase connection URL;
2. derives the IPv4 Session Pooler URL automatically;
3. applies Django migrations;
4. stores the Session Pooler URL in Google Secret Manager;
5. injects the pinned secret version into Cloud Run.

The database already contains the verified Bellissimo canonical dataset.

## Cloud Run

`Dockerfile` builds the Django image.

Cloud Run uses:

`DJANGO_SETTINGS_MODULE=config.settings.cloudrun`

The application listens on the Cloud Run supplied `PORT` and is served by Gunicorn.

Sensitive values are not placed in plain Cloud Run environment variables. The deployment workflow creates new versions of:

- `canecorsoancestry-database-url`
- `canecorsoancestry-django-secret`

in Google Secret Manager and pins the deployed revision to those versions.

## Cloudflare edge

The edge Worker entrypoint is:

`src/cloudrun-edge.js`

Preview configuration:

`wrangler.edge.preview.toml`

Production configuration:

`wrangler.edge.production.toml`

The Worker performs four jobs:

1. serves `/static/*` from Workers Static Assets;
2. proxies normal application requests to the current Cloud Run service URL;
3. exposes the HMAC-authenticated `/_r2/*` backend gateway for Django storage operations;
4. serves short-lived signed `/_media/*` R2 objects after Django authorizes the request.

The Cloud Run container never receives R2 API keys.

## Media flow

Browser requests continue to use Django's normal `/media/<path>` URLs.

Django first checks whether the user is authorized to read the object. If allowed, Django returns a short-lived HMAC-signed Cloudflare edge URL. Cloudflare then streams the object directly from R2.

This keeps media authorization in Django while avoiding a Cloud Run round trip for the actual image/document bytes.

Uploads, existence checks and deletes use `core.cloudrun_storage.CloudflareR2GatewayStorage`, which signs every backend request with the Django secret.

## Required GitHub secrets

Existing secrets remain unchanged:

- `CLOUDFLARE_API_TOKEN`
- `SUPABASE_DATABASE_URL`
- `DJANGO_SECRET_KEY`

No R2 access keys and no Google service-account JSON key are stored in GitHub.

## Required GitHub variables

After the one-time Google setup, add:

- `GCP_PROJECT_ID`
- `GCP_REGION` (recommended: `europe-north1`)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Google authentication uses Workload Identity Federation.

## One-time Google setup

Run:

`bash scripts/setup_gcp_cloudrun.sh PROJECT_ID`

from Google Cloud Shell after creating/selecting a Google Cloud project with billing enabled.

The script:

- enables required APIs;
- creates the Artifact Registry repository;
- applies image cleanup policies;
- creates deploy/runtime service accounts;
- creates Secret Manager secrets;
- grants least-purpose deployment/runtime roles;
- creates a GitHub Workload Identity provider restricted to `eghosa001/canecorsoancestry`;
- prints the GitHub repository variables to add.

## Deployment

Workflow:

`.github/workflows/cloudrun-deploy.yml`

A normal `main` push deploys the **preview edge** only when the Google repository variables have been configured.

Manual workflow choices:

- `preview`: Cloud Run + workers.dev edge
- `production`: same Cloud Run service + Cloudflare custom domains `canecorsoancestry.com` and `www.canecorsoancestry.com`

Every deployment performs:

1. Supabase migration;
2. Docker build and Artifact Registry push;
3. Google Secret Manager version creation;
4. Cloud Run deployment;
5. direct Cloud Run `/healthz/` verification;
6. Cloudflare edge deployment;
7. edge `/healthz/` verification.

## Cost controls

To stay inside free allowances as long as practical:

- Cloud Run minimum instances stays at 0.
- Cloud Run maximum instances is capped at 3.
- Artifact Registry keeps only recent images and removes older images after the configured retention period.
- Secret Manager retains only a small number of enabled versions.
- R2 holds large media outside the PostgreSQL database.

## Cutover order

1. Create/configure the Google Cloud project with `scripts/setup_gcp_cloudrun.sh`.
2. Add the printed GitHub repository variables.
3. Run the Cloud Run workflow with `target=preview`.
4. Verify health, login, admin, member dashboard, dog search, pedigrees, moderation, submissions and media.
5. Run the workflow with `target=production`.
6. Verify `canecorsoancestry.com` end to end.
7. Remove any remaining obsolete infrastructure only after the rollback window has passed.

## Security

- HTTPS-only public traffic.
- Secure Django session/CSRF cookies.
- Supabase Django schema remains private from `anon` and `authenticated`.
- No Supabase service-role key in the application.
- No R2 access keys in Cloud Run.
- Cloudflare R2 gateway uses timestamped HMAC signatures.
- Media delivery uses short-lived signed URLs after Django authorization.
- GitHub authenticates to Google through Workload Identity Federation, not static Google keys.
