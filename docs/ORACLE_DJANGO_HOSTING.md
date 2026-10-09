# Oracle Django hosting: current operations

The Oracle ARM64 VM now hosts both the live Django application and the authoritative local PostgreSQL primary. It is **not just a GitHub runner or staging copy**.

### Services

- `cca-oracle-staging.service` — historical name, but the live Django origin; Podman container `cca-oracle-staging` on loopback port 18080.
- `cca-pg-shadow.service` — historical name, but persistent production PostgreSQL; database `cca_live` in the private `cca-private` Podman network.
- `CCA-ORACLE` — repository-bound GitHub Actions runner on the same VM.
- Cloudflare private VPC Service and Worker — sole public application route, without exposing Django or PostgreSQL ports.

### Routine release

1. Merge reviewed changes to `main` after scoped CI checks.
2. Dispatch `oracle-stage-django.yml` on `main` with `deployment=stage-only`; this **restarts live production Django**.
3. Verify the exact release SHA, database backend `oracle-local`, login, R2 media, production smoke and live data-health workflows.

`scripts/oracle_runner/stage_django.sh` checks that the Oracle-local DB connection is the private, existing `cca_live`. The Supabase environment variable is not needed when `/etc/cca/oracle-db-mode` is `local`.

### Data protection

Retain `oracle-hourly-db-backups.yml`, its off-VM R2 encryption and monthly `database-recovery-drill.yml` integrity check. Do not run the one-time Supabase migration again. Old Northflank and Supabase deployments cannot be considered data-preserving rollback services.

Use `infra/active-services.json` as the tracked service inventory.
