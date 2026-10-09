# Cane Corso Ancestry: Oracle Django staging and cutover

The Oracle GitHub Actions runner is NOT the web server. The new manual workflow
adds an independently managed Podman/Django staging origin on the same ARM64 VM.
Northflank continues serving Cloudflare site-edge traffic until the Oracle
origin is externally reachable, verified, and deliberately selected.

## Safe staging (no production routing change)

1. Merge the PR introducing this document and the staging workflow into main.
2. GitHub Actions > **Oracle Django staging (manual, no cutover)** >
   **Run workflow** > branch **main** > deployment **stage-only**.
3. Follow its run summary; it builds the pinned main SHA on Oracle ARM64,
   resolves the existing Supabase session-pooler connection, checks migration
   parity (without applying migrations), and starts a root-managed systemd
   service named \`cca-oracle-staging\`.
4. It tests \`127.0.0.1:18080/healthz/\`, a trusted sign-in response,
   rejection of untrusted direct traffic, and a temporary R2 upload/read/delete.

The service listens on **127.0.0.1:18080 only**, not the VM's public IP.
The systemd service does not restart, disable, or modify the separate
\`CCA-ORACLE\` Actions runner systemd unit. The VM's 1 vCPU is shared;
application CPU is capped and builds can briefly use the whole remaining CPU.

Secrets are sourced from existing CCA GitHub Actions secrets, then installed as
root-owned \`/etc/cca/oracle-stage.env\` (mode 0600). Never paste values into
tickets or commit them. SMTP is enabled only when all credential secrets exist.
The Supabase \`django_app\` schema and existing Cloudflare R2 gateway stay in use.

**No schema migrations are applied during staging**. Do not run the default
Dockerfile CMD on the staging container: it invokes write-mode migrations.

## Cutover prerequisites (not performed by stage workflow)

- Establish a stable **HTTPS** address to the VM with valid TLS certificate
  and externally verified reachability. Review the OCI security list / NSG and
  firewalld; do not expose PostgreSQL, Gunicorn, the runner or 18080.
- Use a hardened reverse proxy or Cloudflare Tunnel with an owner-approved
  hostname, and permit only Cloudflare-origin traffic where possible.
  Cloudflare Workers cannot reach a loopback-only service.
- Verify public static files, pedigree search, media, sign-in/password reset,
  admin moderation, uploads, Paystack callbacks and CSRF flows through the
  *candidate* Cloudflare route (not by bypassing the Worker).
- Check the exact release SHA, Supabase session persistence, and R2 objects.
  Exercise one harmless test submission and clean it up; do not add production
  dog records just for a smoke test.
- Configure a gated, single-origin Worker change to point \`ORIGIN_URL\` at the
  tested HTTPS hostname. The existing Worker already supports this variable.
  Preserve \`ORIGIN_EDGE_SECRET\`, cache safety, and the current Workers.dev
  public URL. Do not switch traffic merely because localhost staging passes.
- Keep Northflank active at least through the observation/rollback window.
  Disable the Northflank auto-deploy workflow only after a deliberate production
  cutover and documented rollback plan.

## Rollback

Before any cutover, rollback simply means leaving the Worker on the Northflank
origin (nothing to do). To stop the staged Oracle app without affecting Actions:

\`\`\`bash
sudo systemctl disable --now cca-oracle-staging.service
\`\`\`

After a future public cutover, restore Cloudflare site-edge's \`ORIGIN_URL\`
to the known-good Northflank HTTPS endpoint and redeploy the Worker; **do not
delete the canonical Supabase database, R2 media, or Northflank fallback**.

Current Worker default origin:
\`https://web--canecorsoancestry--4w9gl8jxj4yr.code.run\`
