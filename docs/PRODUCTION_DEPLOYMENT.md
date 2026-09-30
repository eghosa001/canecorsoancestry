# Production deployment: Render + Aiven + Cloudflare

This is the production runbook for Cane Corso Ancestry.

## Final architecture

```
canecorsoancestry.com
        |
Cloudflare Worker
   |           |
   |           +--> Cloudflare R2 (media/evidence)
   |
   +--> Render Django origin
             |
             +--> Aiven PostgreSQL
```

Supabase is only the migration source until the Aiven copy is verified. Google Cloud Run and Railway are not active production dependencies.

## Required account values

### Existing GitHub Actions secrets

- `CLOUDFLARE_API_TOKEN`
- `DJANGO_SECRET_KEY`
- `SUPABASE_DATABASE_URL` — keep only until migration is complete

### New GitHub Actions secret

- `AIVEN_DATABASE_URL` — exact Aiven PostgreSQL Service URI

### New GitHub Actions variable

- `RENDER_ORIGIN` — the exact HTTPS Render URL, for example `https://canecorsoancestry.onrender.com`

The `DJANGO_SECRET_KEY` value in Render must be exactly the same value as the GitHub Actions secret because the Cloudflare Worker and Django use it to authenticate edge and R2 requests.

## 1. Create Aiven PostgreSQL

1. Sign in to Aiven.
2. Create or select a project.
3. Open **Services** and choose **Create service**.
4. Select **PostgreSQL**.
5. Select the **Free** tier/plan.
6. Name the service `canecorsoancestry-db`. Aiven service names are not renamed in place, so choose the name carefully.
7. If PostgreSQL version selection is offered, choose the newest stable version Aiven offers on the Free plan. The migration workflow reads both server versions and refuses to migrate into an older PostgreSQL major version.
8. On the Free tier Aiven assigns the cloud/region; do not upgrade just to choose a region.
9. Create the service and wait until its status is **Running**.

Do not create a `django_app` schema manually. The migration workflow intentionally requires an empty target and restores that schema from Supabase.

## 2. Copy the Aiven Service URI

1. Open the PostgreSQL service.
2. Open **Overview**.
3. Choose **Quick connect** or **Connection information**.
4. Copy the complete **Service URI**.

It has this shape:

```
postgres://avnadmin:<password>@<service>.aivencloud.com:<aiven-port>/defaultdb?sslmode=require
```

Use the URI exactly as Aiven provides it. The port is service-specific and is not necessarily 5432.

Do not commit the URI to the repository.

## 3. Add the Aiven URI to GitHub

In GitHub:

1. Open `eghosa001/canecorsoancestry`.
2. Go to **Settings → Secrets and variables → Actions**.
3. Open **Secrets**.
4. Choose **New repository secret**.
5. Name it exactly:
   `AIVEN_DATABASE_URL`
6. Paste the complete Aiven Service URI.
7. Save it.

Keep `SUPABASE_DATABASE_URL` in place for now. The migration workflow needs both source and destination.

## 4. Run the one-time Supabase → Aiven migration

In GitHub:

1. Open **Actions**.
2. Select **Migrate Supabase database to Aiven**.
3. Choose **Run workflow**.
4. Enter:
   `MIGRATE_TO_AIVEN`
5. Run it.

The workflow deliberately:

- validates the Aiven URI;
- compares the Supabase and Aiven PostgreSQL major versions and refuses a downgrade target;
- automatically uses the Aiven target major version's PostgreSQL client for dump/restore;
- discovers a reachable Supabase session-pooler source;
- confirms the Supabase Django migrations are current;
- refuses to continue if Aiven already contains the `django_app` schema;
- installs `pg_trgm` on Aiven;
- dumps only the private `django_app` schema from Supabase;
- restores that schema and its data to Aiven;
- compares every Django table and row count between Supabase and Aiven;
- runs Django deployment checks against Aiven.

Do not switch Render to Aiven unless this workflow finishes successfully.

## 5. Create or update the Render service

### New Render service

1. Sign in to Render.
2. Connect GitHub if it is not connected.
3. Create a **Blueprint** from `eghosa001/canecorsoancestry`.
4. Render detects the root `render.yaml`.
5. Create the `canecorsoancestry` free web service.
6. When prompted for `DATABASE_URL`, paste the exact Aiven Service URI.
7. When prompted for `DJANGO_SECRET_KEY`, paste the same value stored in GitHub Actions.
8. Deploy.

### Existing Render service

If the service already exists, open **Environment** and change:

- `DATABASE_URL` → Aiven Service URI
- verify `DJANGO_SECRET_KEY` matches the GitHub Actions secret

The Blueprint already supplies:

- `DJANGO_SETTINGS_MODULE=config.settings.render`
- `DJANGO_DB_SCHEMA=django_app`
- `DJANGO_DB_SSLMODE=require`
- `DJANGO_DB_EXTRA_SCHEMAS=public`
- `REQUIRE_CLOUDFLARE_EDGE=1`
- the R2 gateway settings

After deployment, copy Render's exact external URL from the service page. It will be an HTTPS `onrender.com` URL.

Expected checks:

- `<render-origin>/healthz/` → HTTP 200
- `<render-origin>/` → HTTP 403 because normal application traffic must come through Cloudflare

## 6. Add the Render origin to GitHub

In **Settings → Secrets and variables → Actions → Variables**, create:

`RENDER_ORIGIN`

Set it to the exact Render external URL, with no trailing path. Example:

`https://canecorsoancestry.onrender.com`

This is a variable, not a secret.

## 7. Deploy the production Cloudflare edge

In GitHub Actions:

1. Open **Cloudflare edge and R2 gateway**.
2. Choose **Run workflow**.
3. Set target to **production**.
4. Run it.

The workflow:

- builds static assets;
- verifies/creates the `canecorsoancestry-media` R2 bucket;
- deploys the production Worker;
- binds `canecorsoancestry.com` and `www.canecorsoancestry.com`;
- proxies dynamic traffic to `RENDER_ORIGIN`;
- verifies the public health endpoint;
- verifies direct Render application traffic returns 403.

The Worker custom domain owns the public domain. Do not separately point `canecorsoancestry.com` directly at Render while using this edge architecture.

## 8. Verify the application before retiring Supabase

Verify at minimum:

- homepage;
- dog search;
- dog profile;
- pedigree pages;
- sibling/offspring navigation;
- member login;
- dashboard;
- Django admin;
- image/media display;
- image upload path if applicable;
- moderation queue;
- one harmless database write followed by a read.

After cutover, new writes exist only in Aiven. Supabase is no longer a live replica.

Keep the Supabase project temporarily as a pre-cutover snapshot, then retire it after the Aiven-backed site has been checked.

## 9. Post-cutover cleanup

After Aiven + Render + Cloudflare have been verified:

1. Remove the GitHub Actions secret `SUPABASE_DATABASE_URL`.
2. Delete the one-time `.github/workflows/aiven-migrate.yml` workflow and Supabase discovery helper in a later cleanup PR.
3. Pause/delete the Supabase project only after you are satisfied the Aiven copy is complete.
4. Keep `AIVEN_DATABASE_URL`, `DJANGO_SECRET_KEY`, and `CLOUDFLARE_API_TOKEN`.
5. Use **Seed production Bellissimo data** and **Sync Bellissimo media to R2** only when intentionally required.

## Free-tier constraints

Aiven Free currently has a low PostgreSQL connection limit and no connection pooler. The Render service is therefore intentionally configured with one Gunicorn worker and two threads.

Render Free spins down after inactivity, so the first request after an idle period can be slow. The application's persistent state is unaffected because the database is in Aiven and media is in R2.

Aiven can power off long-unused free services after notification. If that ever occurs, power the database service back on from the Aiven console.

## Using another AI with Aiven

Aiven provides an official hosted MCP server at:

`https://mcp.aiven.live/mcp`

A compatible assistant such as Claude Code, Cursor, VS Code or Gemini CLI can use it to create and inspect Aiven services.

For a production database, use the AI to create/configure the service, but avoid enabling Aiven's connection-credential exposure option unless you explicitly accept that security tradeoff. The safer approach is to copy the Service URI yourself from Aiven and paste it directly into GitHub Secrets and Render.

Suggested prompt:

```
Create a free Aiven for PostgreSQL service for my Django project Cane Corso Ancestry.
Name it canecorsoancestry-db. Do not create application tables or a django_app
schema and do not delete or modify any existing service. Confirm the plan is Free,
the service is Running, PostgreSQL supports pg_trgm, and tell me where in the Aiven
console I should copy the Service URI. Do not print the database password or URI in
chat.
```
