# Cane Corso Ancestry — final production pass (11 October 2026)

## Scope and evidence

Baseline `main` release: `3a8e84392676b935f9983197750dc95042e01ac4` (10 October 2026 23:58 UTC). Public application: https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev . This review concerns **Cane Corso Ancestry only**, not the separate BellissimoGeni website. Live figures and checks below are from the completed GitHub Actions runs, not estimates or recycled older scan results.

- [Full release audit](https://github.com/eghosa001/canecorsoancestry/actions/runs/38096837138): SQLite and PostgreSQL 17 Django suites plus dependency/edge jobs all **success**.
- [CI-gated Oracle release](https://github.com/eghosa001/canecorsoancestry/actions/runs/38096906059): **success** at that exact main SHA.
- [Production data health](https://github.com/eghosa001/canecorsoancestry/actions/runs/38096946049): **success**; completed 11 October at approximately 00:02 UTC.
- [Production smoke](https://github.com/eghosa001/canecorsoancestry/actions/runs/38096946059): **success**; Chromium, Firefox and WebKit browser checks, public route checks and captured artifacts.
- [Safari-focused compatibility](https://github.com/eghosa001/canecorsoancestry/actions/runs/38096742277): **success** for mobile dog-photo changes.
- [Encrypted offsite backup](https://github.com/eghosa001/canecorsoancestry/actions/runs/38120689478): **success** at 07:14 UTC on 11 October; encrypted R2 archive and latest recovery pointer both verified.

These prove the **last deployed main release**, not this review branch. Neither a green CI job nor a browser-emulation screenshot proves end-to-end authenticated production behavior on an actual iPhone, operational SMTP delivery or Paystack settlement. Independent read-only browsing was unavailable in the review session; the linked Actions jobs are the direct-production evidence.

## Live data-quality snapshot (11 October 00:01–00:02 UTC)

| Metric | Measured value | Interpretation |
| --- | ---: | --- |
| Public canonical dog records | 33,241 | Records, not independently verified identities |
| Public dogs with connected pedigree | 31,964 (96.16%) | Links present; completeness outside recorded graph unknown |
| Public dogs with displayable photographs | 9,653 (29.04%) | **23,588** public records are pedigree-only/no displayable photo |
| Public records with source metadata | 33,238 (99.99%) | **Three** missing metadata; metadata is not evidence review |
| Independently verified source-backed public records | **0** | Critical trust/verification coverage gap, not zero imported sources |
| Canonical litter duplicate groups | 0 | Live invariant checked |
| Duplicate kennel-name groups | 0 | Live invariant checked |
| Conflicting sire sex / dam sex / parent dates | 0 / 0 / 0 | Live audit checked |
| Staff/member identity overlap | 0 | Live invariant checked |
| Litter/member parent or birth-date conflicts | 0 | Live invariant checked |
| Sampled rendered media | 22/22 valid HTTP images | Sample only; not a bucket-wide audit |
| COI live checks | 6 completed | A known public calculation returned 2.510267% and displayed 2.51% |
| COI identity exceptions | 1 needs review | Faro Olimpo archive/canonical candidate; **do not merge automatically** |

The low photo ratio and zero independently verified records are **content and evidence-governance gaps**. Do not fabricate images, dates, COI ancestors or verification badges in order to improve these ratios. A legitimate published dog with no photograph must remain discoverable through explicit search.

## Change set proposed by this review

1. Authentication abuse limiter: trust `X-Forwarded-For` only if the Cloudflare edge marker **and** shared origin secret authenticate the request; otherwise key by `REMOTE_ADDR`. Added focused regression tests for forged and authenticated forwarded addresses.
2. Public language: replace “Other registered offspring” with “Other offspring without photos”; the site is not a registration authority.
3. Remove duplicated `default_storage` import. No database rows, migrations, external integrations or design-system files changed.

## 54-subcategory benchmark — evidence status

Statuses: **Evidence** = checked directly in linked CI/live smoke for a meaningful part of the surface; **Partial** = implementation exists but full acceptance criteria not proven; **Open** = required quality evidence or content coverage missing. None of these labels asserts a numeric score of 9+/10.

### A. Public UI and UX (11)

| Subcategories | Evidence status / action |
| --- | --- |
| Brand identity; homepage hierarchy; desktop layout | Partial: design references exist; require owner-reviewed production screenshots |
| iOS/Android responsiveness; navigation | Evidence (browser emulation), open actual iPhone/Android hardware walkthrough |
| Public search | Evidence (live query and browser), open production autocomplete and large-result usability |
| Dog profile presentation; photos/galleries | Evidence (22 media assets + WebKit regression), open real-device pinch/scroll stability |
| WCAG accessibility | Partial: smoke coverage, open full keyboard/screen-reader acceptance |
| Interactive response/feedback; newcomer onboarding | Partial: conduct anonymous first-visit task study |

### B. Pedigree and breeding research (11)

| Subcategories | Evidence status / action |
| --- | --- |
| Tree visualization; generation depth (4/6/8/10); ancestor contribution/linebreeding | Partial: require deep known-family fixtures and real-device navigability |
| Wright COI and coverage | Evidence for six live graphs and one rendered percentage; open comprehensive known pedigree parity audit |
| Reverse descendants; virtual mating; siblings/offspring/mates | Partial: implementation/tests present; live authenticated end-to-end acceptance remains |
| Verified health/DNA context | Open: distinguish imported claims from reviewed evidence |
| Reports/export; saved breeding plans; multi-dog comparisons | Partial: verify owner task completion, correctness, and mobile layout |

### C. Database and evidence trust (7)

| Subcategories | Evidence status / action |
| --- | --- |
| Canonical breadth | Evidence: 33,241 public dogs, not a claim of population completeness |
| Pedigree-link completeness | Evidence: 31,964 linked, without asserting unrecorded ancestors |
| Photograph completeness | Open: 29.04% displayable; acquire and review licensed/authorized photos |
| Import/source provenance | Evidence: 33,238 metadata-backed, three missing |
| Human evidence verification | **Open: zero independently verified source-backed public records** |
| Duplicate resolution | Partial: no duplicate canonical litters; one candidate must be manually investigated |
| Pedigree integrity (cycles, sex, date, identity) | Evidence for checked live invariants, incomplete external factual corroboration |

### D. Members and kennels (8)

| Subcategories | Evidence status / action |
| --- | --- |
| Email registration/reset | Partial: route/unit tests pass; confirm **real outbound production email** before declaring ready |
| Dashboard navigation | Partial: role/browser tests exist; authenticated customer field verification remains |
| Ownership claims/kennel roles; dog/photo/health/document submissions | Partial: access separation tests, open sampled owner/editor/contributor tasks |
| Review status/evidence requests | Partial: test with real but reversible moderation cases |
| Payment entitlements | Partial: Paystack unit checks; test actual sandbox callback, webhook, amount and idempotency |
| Research engagement/retention | Open: no field adoption measure for saved workflows |
| Privacy, consent and separate staff accounts | Evidence for zero current role overlap; expand forbidden-action regression fixtures |

### E. Admin and moderation (9)

| Subcategories | Evidence status / action |
| --- | --- |
| Super Admin workspace; searchable queues | Partial: audited code/tests, field verify large queue performance |
| Warnings/second reviewer; disputes | Partial: role/verification tests, real account journeys needed |
| Role boundaries | Evidence in code and live identity invariant; test direct access rejection after session changes |
| Canonical edit safeguards | Evidence in focused tests: Super Admin publication toggle, audit and stale-version rejection |
| Merge and preservation | Partial: maintain pre-merge review; never auto-merge the Faro Olimpo candidate |
| Audit immutability | Partial: implementation checks exist, independent audit review required |
| Moderator navigation/productivity | Open: measure realistic review work rather than screenshots alone |

### F. Engineering and operations (8)

| Subcategories | Evidence status / action |
| --- | --- |
| Authentication/security | Evidence for secure production settings and tests; proposed rate-limit hardening must pass CI |
| Response latency | Partial: measured synthetic routes, not real-user p75/p95 comprehensive SLOs |
| Production reliability | Evidence: live health and 11 October release smoke successful |
| Committed update freshness | Evidence: exact main SHA deployed; open eventual propagation on real client devices |
| Automated real-browser coverage | Evidence: Chromium/Firefox/WebKit successful; not substitute for real devices |
| Backup and restore | Evidence: hourly encrypted archive uploaded and pointer verified; **restore drill result not established by this snapshot** |
| SEO | Partial: basic metadata, sitemap and route checks; no verified search-ranking outcome |
| Media delivery/integrity | Evidence: sampled 22/22 success; 23,588 public dogs remain without displayable imagery |

## Release decisions

**Required before an unqualified “9+/10 fully production-ready” claim:**

1. Confirm working email verification and password recovery delivery on the live sender, without logging secrets or reset tokens.
2. Verify Paystack sandbox purchase, duplicate webhook, insufficient payment, staff approval gating and refund exception workflows. Never purchase real packages merely to test.
3. Investigate Faro Olimpo and the three metadata-free public dogs manually; preserve canonical identities and all history.
4. Build a rights-respecting photo/evidence enrichment queue rather than hiding valuable photo-less pedigree records.
5. Complete a real backup **restore drill** to isolated infrastructure and preserve the production primary untouched.
6. Run actual signed-in owner, contributor, reviewer and Super Admin journeys, plus mobile Safari hardware and keyboard/accessibility checks.
7. Measure uncached public p95, authenticated p95, and real-user p75 Core Web Vitals before claiming performance at 9+.

**Deployment safety:** Oracle-local PostgreSQL stays authoritative; retired Northflank/Supabase are never fallback targets. Do not merge stale PR #101 (Northflank cutover) or other historical branches without a modern rebase and explicit functional review.

**Review branch validation:** focused `core.tests_security_hardening.SecurityHardeningTests`, appropriate template/copy check, and existing required PR checks. Do not rerun redundant suites manually or bypass the repo's fast-path policy.

**Conclusion:** The baseline main release passed strong live production and CI checks. The site is **operational, but not independently certified 9+/10**: record evidence coverage, photo completeness, verified real-user account/payment flows and disaster-recovery rehearsal remain open. Keep a measured scorecard, not an invented overall grade.
