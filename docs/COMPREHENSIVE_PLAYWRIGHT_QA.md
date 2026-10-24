# Comprehensive Playwright audit (isolated CI)

Workflow: `.github/workflows/comprehensive-playwright-audit.yml`.

This workflow is intentionally a **testing system, not a production agent**. It
cannot responsibly certify the 20-phase brief until every discovered route and
UI action has its own automated assertion. The inventory and final reports
explicitly flag remaining test gaps.

## Automated execution

- On pull requests and pushes to main.
- On a weekly schedule and on manual GitHub Actions dispatch.
- Full Django test modules (`accounts`, `registry`, `pedigrees`, `core`)
  in separate jobs. This includes existing payment-mock, authorization,
  pedigree/COI and document-upload regression tests.
- Independent Playwright Chromium, Firefox and WebKit jobs, each using its
  own migrated SQLite database and disposable media directory.
- Existing role audit that exercises member and staff navigation, moderation
  approval, and synthetic dog merge in isolated local browsers.
- Browser journeys for signup verification and password-reset mail,
  draft dog creation with a genuine JPEG, real PNG photo upload plus forged
  JPEG rejection, persisted submissions, cross-account access restrictions,
  editor permissions, staff identity boundaries and Django Admin dog details.
- Dynamic inventory of Django URLs and registered Admin models, including
  those not yet covered by end-to-end browser assertions.
- JUnit, HTML, screenshots, failure traces, Django logs and final dashboard
  uploaded as GitHub Actions artifacts. Missing matrix jobs and skipped
  expected browser cases fail the consolidated report.

## QA identities and email

`scripts.seed_browser_audit` provisions Member, Reviewer, Senior and Owner.
`scripts.qa_extended_seed` adds Member 2, Editor, Contributor and an independent
Reviewer, plus synthetic dog photos and a PDF. The run-local credentials
file is `/tmp/cca-playwright-audit-credentials.json` and is never uploaded.
`example.test` email addresses are deliberately not deliverable on the
Internet. Django's **file-based** email backend writes verification and reset
emails to a private job-local mailbox; the browser audit reads the links and
verifies activation. No Gmail inbox or real email delivery is required.

The test JPEG and PNG are generated with Pillow on the runner, rather than
loading potentially broken external source images. An invalid JPEG is also
generated to verify rejection. The isolated media tree is discarded with
the runner; no real kennel or dog data is altered.

## Payment safety

No live Paystack credentials are installed. All payment lifecycle tests run
from the existing `accounts.tests_payments` backend suite with deterministic
gateway stubs and signed mocked webhooks. The CI browser test intentionally
cannot initiate a real external checkout. A full live-provider sandbox journey
requires a separately configured test gateway and has **not** been claimed as
covered.

The current code uses `SubmissionPayment.LITTER_PRICE_KOBO = 150000` (₦1,500).
Some older repository documentation still says ₦1,000: the test system must
validate the implementation, and the product owner should reconcile the policy.

## Interpreting the evidence

- A route in `feature-inventory.json` is **discovered**, not automatically
  tested. The inventory marks it `NOT_TESTED` until its behavior is proven.
- `cases-<browser>.json` shows which named browser workflows passed or
  failed. `junit-<browser>.xml` and trace archives provide reproducible
  failure evidence.
- `backend-*.log` contains the actual Django assertions for each app.
- `dashboard.json` intentionally reports `all_routes_tested: false` and
  `all_20_phases_completed: false` until a route-to-action coverage system
  proves those claims.

Review the report before merging or deploying. Do not weaken security
checks, mark a payment paid by hand, or enable production mutation to
make a CI test green.
