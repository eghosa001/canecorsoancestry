# Cloudflare production origin migration and rollback

Oracle Django staging, private Tunnel, VPC Service and guarded Oracle Worker
were verified successfully on 9 October 2026. The public Worker currently
uses Northflank until an explicit production cutover.

The regular Cloudflare site-edge workflow now **preserves whichever origin is
live**, determined by the production /__edge/health endpoint before each
Worker deployment. If the endpoint fails or reports an unexpected origin, the
workflow stops rather than silently changing production back to Northflank.

## Manual cutover

1. Merge the reviewed production-cutover preparation PR on main.
2. GitHub Actions → **Oracle production cutover / Northflank rollback
   (manual)** → Run workflow → main → **switch-to-oracle**.
3. The job tests the authenticated-ready private Oracle candidate, performs
   an invalid login POST to confirm CSRF and form handling, then deploys the
   **existing public Worker** bound to the tested private Oracle VPC Service.
4. It verifies exact origin/version, authenticated readiness, home, login,
   virtual mating, and CSS on the public workers.dev URL. On validation
   failure it attempts to restore the previous origin automatically.

For emergency rollback run the same workflow selecting
**rollback-to-northflank**. Northflank remains live until separately retired.

**Operations:** Oracle Django staging remains a manual, protected-main
workflow. Before application releases while Oracle is production, run that
staging workflow on the intended main revision; Northflank auto-deploying
alone does not update the Oracle container. Monitor password reset SMTP,
Paystack callbacks, authenticated uploads/R2 and real sessions before
decommissioning Northflank.

No public VM web ports, separate domain or self-hosted PR runner required.
