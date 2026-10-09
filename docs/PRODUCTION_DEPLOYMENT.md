# Production deployment runbook — Oracle + Cloudflare + R2

## Active stack

The public Cloudflare Workers site edge routes exclusively to Django on Oracle through the private VPC Service. Django uses the local `cca_live` PostgreSQL database. R2 remains the media and encrypted offsite-backup store.

Source of truth: `infra/active-services.json` and `scripts/verify_active_services.py`.

- Public site: `https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`
- R2 gateway: `https://canecorsoancestry-edge.aighewieghosa111.workers.dev`
- Oracle Django service: `cca-oracle-staging.service` (historical service name, **production origin**)
- Oracle PostgreSQL service: `cca-pg-shadow.service` (historical service name, **production primary**)
- Database: `cca_live`; mode `/etc/cca/oracle-db-mode = local`
- Private app listener: `127.0.0.1:18080` on Oracle, accessed through Cloudflare VPC only

## Deploy a Django release

1. Merge a reviewed PR to protected `main` after focused CI and DB/release checks.
2. Run **Oracle Django staging (manual, no cutover)** → `stage-only` from `main` (`.github/workflows/oracle-stage-django.yml`). Despite the legacy workflow name, this **restarts the production Oracle Django container** while leaving Cloudflare routing unchanged.
3. Confirm the workflow verifies the exact commit SHA, local database, sign-in and R2 media storage.
4. Run the production smoke and production data-health workflow. Confirm `/__edge/health` reports `origin=http://127.0.0.1:18080` and `/healthz/` reports `database_backend=oracle-local`.

Do not infer Django deployment from a Cloudflare edge deployment. No Northflank workflow builds the live application.

## Deploy a Cloudflare Worker

- Public edge: `.github/workflows/cloudflare-site-edge.yml` (only on Worker/config changes or manual dispatch). It refuses to deploy if the existing live Cloudflare bindings are not for Oracle.
- Media gateway: `.github/workflows/cloudflare-media.yml`; preserve existing R2 signing configuration.

Worker configuration pins Oracle's private VPC service. Never set the origin to the former Northflank public URL.

## Data protection and recovery

- `.github/workflows/oracle-hourly-db-backups.yml`: hourly encrypted live local PostgreSQL snapshots to Cloudflare R2; rotating archives retained for seven days.
- `.github/workflows/database-recovery-drill.yml`: monthly read-only download/decryption/archive integrity check of the latest offsite snapshot. **Not** a full isolated restore rehearsal.
- `.github/workflows/production-data-health.yml`: checks the local primary, live Django schema, pedigree and ownership invariants plus public images and password recovery.
- Restoring a database requires a separate isolated rehearsal and a controlled downtime/recovery plan. Never restore over `cca_live` in place without safeguards.

The historical Supabase and Northflank stacks are not data-preserving rollback targets after Oracle accepted writes; their old database is not synchronized. Retired one-shot migrations must not be re-run.

## Secrets and access

Secrets remain in GitHub Actions and root-owned files under `/etc/cca/` on Oracle. Do not print credentials, put them in docs, or commit them.

Runtime uses `DJANGO_SECRET_KEY`, `PAYSTACK_SECRET_KEY` when billing is enabled, SMTP credentials for account recovery, and an authenticated R2 gateway signing key. Oracle-local DB credentials are VM-local and should **not** be copied to GitHub.

Oracle VM application/database ports are not public, and the self-hosted runner should only execute trusted `main` production operations.

## Checks

```bash
python3 scripts/verify_active_services.py
python3 scripts/fast_path_guard.py
node scripts/test_site_edge_cache.mjs
python3 -m unittest scripts.tests.test_edge_origin_mode
```
