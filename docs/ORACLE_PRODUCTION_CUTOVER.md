# Oracle production origin: current state and decommission warning

As of 9 October 2026, Cloudflare's public Worker is **already** routed to Oracle via the private VPC Service (verified by Cloudflare edge deployment run 37904020566 and production smoke 37904137735). Oracle also hosts the **authoritative local PostgreSQL** database.

The earlier Northflank-to-Oracle cutover procedure has completed. Its one-time manual cutover/rollback workflow was removed during infrastructure consolidation.

**Never use the old Northflank/Supabase instance as a production rollback target.** Since the local database became authoritative, new dog, membership, login, payment and moderation data are in Oracle-local `cca_live`. The frozen Supabase source and an older Northflank deployment are stale, not lossless replicas. Switching traffic to them would expose outdated application records.

For releases use `.github/workflows/oracle-stage-django.yml` on protected `main`; it updates the Oracle production container and does not change Cloudflare routing. For media recovery and database integrity use the hourly encrypted R2 archives, the recovery-integrity workflow, and the documented controlled restore process.

See `infra/active-services.json`, `ARCHITECTURE.md` and `docs/PRODUCTION_DEPLOYMENT.md` for the current authoritative configuration.
