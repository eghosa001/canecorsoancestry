# Cane Corso Ancestry architecture

## Production architecture — 9 October 2026

```text
Browser / mobile
      |
      v
Cloudflare Workers site edge (cache, auth-safe proxy)
      |
      | Private Cloudflare VPC Service (NOT VM public TCP)
      v
Oracle VM: Django / Gunicorn / WhiteNoise (Podman, 127.0.0.1:18080)
      |
      +-- Oracle-local PostgreSQL 17 (cca_live, private cca-private network)
      |
      +-- Cloudflare media Worker --> R2 images, evidence, documents
                                      + encrypted hourly PostgreSQL backups
```

Live Django and its database are local to the **Oracle VM**. Supabase is an old frozen source, not a replica or writable production DB. Northflank is no longer the production application host; restoring its old service would reconnect to a stale database and is **not** a safe data-preserving rollback.

## Runtime components

| Service | Current responsibility | Configuration |
| --- | --- | --- |
| Cloudflare site Worker | Public URL, caching, VPC routing, origin guards | `src/site-edge.js`, `wrangler.site.toml` |
| Oracle Django | Live web application, authenticated member/admin routes | `scripts/oracle_runner/stage_django.sh`, `scripts/oracle_runner/oracle_settings.py` |
| Oracle PostgreSQL | Authoritative dog, pedigree, memberships, sessions, payments and audit records | `/etc/cca/oracle-db-mode` (`local`), `/etc/cca/pg-live-app.env` (VM only) |
| Cloudflare R2 media Worker | Private photos and verification files | `src/r2-media.js`, `wrangler.r2.toml` |
| Cloudflare R2 offsite backup | Encrypted hourly database archives, seven-day rolling retention | `scripts/oracle_runner/backup_local_postgres.sh` |
| GitHub Actions / CCA-ORACLE runner | CI, protected release, health and offsite recovery integrity | `.github/workflows/` |

Media routes include `/healthz/`, authenticated `/_r2/*`, and signed `/_media/*`. The public Django media route authorizes access before redirecting. No public database or app ports should be opened on Oracle.

## Django applications

- `core`: site shell, homepage, security, member overview and media authorization.
- `accounts`: member profile, uploads, payments, submissions, moderator and super-admin workspaces.
- `registry`: canonical dog/kennel/litter records, source evidence, health, images, search, audit.
- `pedigrees`: ancestry/descendant traversal, COI and virtual mating.

## Operational invariants

- Never deploy or write new production data to Northflank or Supabase.
- Never automatically switch the Cloudflare Worker away from Oracle's private VPC binding.
- Protect the live `cca_live` database; do not re-run one-time migration scripts or restore over it.
- Do not claim a healthy production database based on tests run against Supabase.
- Oracle application updates require a protected manual deploy on `main`.
- Offsite encrypted backups and checks remain enabled. Recovery integrity checks do **not** constitute a full isolated restore test.

The tracked authoritative inventory is `infra/active-services.json`, validated by `python3 scripts/verify_active_services.py`.
See `docs/PRODUCTION_DEPLOYMENT.md` for current release and disaster-recovery instructions.
