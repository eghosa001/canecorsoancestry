# Commercial domain launch gate

The weekly/manual `Production launch integration gate` is intentionally
negative if production email verification, SMTP credentials, Paystack, HTTPS or
a verified support email is not configured. It does not send actual mail or
charge cards; those tests require real delivery and Paystack sandbox access.

- Configure `CCA_SUPPORT_EMAIL` as a monitored public support address in
  GitHub repository variable `CCA_SUPPORT_EMAIL`; Oracle release injects it
  into its protected runtime environment.
- Have an appropriately qualified adviser finalize Privacy, Terms, Payments and
  Refund text with the legal operator identity, retention and complaints terms.
- Test delivery of account verification and password-reset emails to a real
  mailbox; configuration checks alone are insufficient.
- Complete Paystack sandbox payment, signed callback, duplicate webhook, refund
  policy and customer support/receipt journeys; do not charge real cards.
- After buying the domain, add Worker custom hostname/TLS, update SITE_URL,
  allowed hosts, CSRF origins, Paystack callback, email SPF/DKIM/DMARC,
  canonical redirect, sitemap and Search Console.
- Retain backup freshness monitoring and a successful isolated PostgreSQL
  recovery drill; verify exact deployed SHA and authenticated mobile journeys.

A missing commercial prerequisite is an explicit BLOCK, not a false PASS.

## Purchased production domain: canecorsoancestry.com (Spaceship)

The domain is purchased, but **registration does not prove working Cloudflare DNS**.
The active zone uses the following routing:

- `canecorsoancestry.com` — canonical website via `wrangler.site.toml`.
- `www.canecorsoancestry.com` — **existing Cloudflare DNS-managed redirect** to the apex, preserving path/query; do not bind another Worker Custom Domain over that record.
- `media.canecorsoancestry.com` — the existing private, HMAC-signed R2 gateway.

Cloudflare must first show the zone as **Active**. At Spaceship set the exact
two nameservers assigned **to this zone** by Cloudflare; do not guess or use
the nameservers assigned to a different site. Cloudflare Workers Custom
Domains create their proxied DNS records and TLS certificates on deployment.
Retain the working DNS-managed `www` redirect; do not delete its DNS records.

**Required release order:** Active Cloudflare zone → deploy and verify site
and media Custom Domains/TLS → verify real Django login, /healthz/,
sitemap and media signatures on the new hostnames → release Oracle with
SITE_URL, trusted hosts/CSRF and media gateway set to the purchased domain →
confirm Paystack callback, account email URLs and Google Search Console →
enable old workers.dev website host redirects and retain private operational
health/asset routes. The production Oracle staging script fails closed if
official site or media routes are not live. Do not remove the R2 worker,
database or Oracle tunnel; these are essential services rather than old sites.

Old public Workers website pages become 308 redirects after the site Worker
deploys with DOMAIN_REDIRECTS_ENABLED=1. Previously issued signed image URLs
are allowed to expire naturally through the legacy media Worker. Do not
turn off its workers.dev route until no old signed image/backup clients need it.
