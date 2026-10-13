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
