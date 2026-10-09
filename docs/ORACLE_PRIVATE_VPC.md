# Oracle Django private Cloudflare VPC candidate

Cloudflare Workers VPC (beta, Oct 2026) connects the existing public Worker
to an Oracle service through an outbound-only Cloudflare Tunnel. No public
Oracle web ports or new custom domain are needed.

The CCA Oracle localhost-only Django staging must pass first.

1. Merge this preparation PR.
2. Manually run **Oracle private VPC candidate (manual, no cutover)** on
   protected main, with operation prepare-candidate.
3. The ARM64 job creates/reuses cca-oracle-private-vpc and installs a separate
   cca-cloudflared-vpc systemd service. The tunnel token stays root-only.
4. The GitHub-hosted job creates/reuses cca-oracle-django-local, a VPC service
   limited to 127.0.0.1:18080. It deploys a *different* Worker named
   canecorsoancestry-oracle-candidate, guarded against unauthenticated traffic.
5. The smoke test confirms private routing, sign-in, pedigree, and CSS
   through the candidate, with no public production traffic changed.

If the existing Cloudflare API token lacks Cloudflare Tunnel Write or
Connectivity Directory Admin, the action will stop safely and report the
permissions issue. Avoid copying tunnel credentials into chat or source code.

A separate deliberate cutover is required: the existing public Worker must
then use the verified VPC binding and private origin, and the normal Worker
deployment workflow must be made origin-aware so future automatic builds do
not switch back to Northflank. Test authenticated POST/CSRF, uploads, Paystack,
password reset, and static/media routes before switching. Retain Northflank
during rollback observation. Do not remove the GitHub Actions runner.

References:
https://developers.cloudflare.com/workers-vpc/get-started/
https://developers.cloudflare.com/api/resources/connectivity/subresources/directory/subresources/services/methods/create/
