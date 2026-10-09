# Cane Corso Ancestry — permanent 9+/10 comparative quality benchmark

Owner-approved comparison standard, established **9 October 2026**. This document is binding on future Cane Corso Ancestry product, Django admin, member, pedigree, design and operations changes. Read alongside `SKILL.md`, `docs/PRODUCTION_QUALITY_STANDARDS.md`, `docs/PEDIGREE_FEATURE_PARITY.md` and the approved visual references in `docs/design-reference/`.

## Competitive reference set

Evaluate the workflows (not imitation of branding) against:

1. Cane Corso Pedigree Database — specialist breed coverage, ancestry research and historical data.
2. Pedigree Online — advanced pedigrees, configurable permissions, reports and genealogy workflows.
3. Pedigree Database — public community discovery and dog record accessibility.
4. The Breed Archive — ancestry interaction, reverse pedigree, saved research and test matings.
5. K9Data — detailed breed research, genetic/health context and family comparisons.

External capabilities, counts and current UI **must be reverified when scoring**. Never invent current competitor statistics. Some offerings are paid, breed-specific or differently scoped; do not penalize this site for refusing to become a registry, classified site or forum.

## Original baseline (provisional, 9 October 2026)

| Category | Baseline (/10) | Target |
|---|---:|---:|
| Public UI and UX | 7.4 | >=9.0 |
| Pedigree and breeding research | 7.1 | >=9.0 |
| Database coverage and evidence trust | 7.0 | >=9.0 |
| Member and kennel-owner experience | 7.7 | >=9.0 |
| Moderation, Super Admin and governance | 8.2 | >=9.0 |
| Engineering, availability and security | 7.8 | >=9.0 |
| Overall (equal-category approximate) | 7.5 | >=9.0 |

**Scores are an initial expert estimate, not verified 9+ achievements.** Source evidence: inspected main-branch code, GitHub Actions and the 9 October production data-health audit. Authenticated real-account user testing and real-device visual testing were not completed for every screen. Do not turn these scores into permanent claims. Reassessment must include evidence URLs, release SHA, date, reviewer, and gaps.

Production historical baseline (9 Oct): 33,255 public dogs; 31,964 with public pedigree links (96.1%); 9,652 with displayable photos (~29%); two public dogs without source metadata; zero database records counted as independently verified source-backed. Source metadata **is not** independently verified evidence. Do not falsely promote data, remove photo-less ancestry, or create duplicates to improve ratios.

## Mandatory review inventory — score every subcategory 0–10

### A. Public UI/UX (11)
Brand identity; homepage hierarchy; desktop layout; iOS/Android responsiveness; navigation; public search; dog profile presentation; photos/galleries; WCAG accessibility; interactive response/feedback; newcomer onboarding.

### B. Pedigree research (11)
Tree visualization; 4/6/8/10-generation depth; Wright COI and coverage disclosures; ancestor contribution/linebreeding; reverse descendants; virtual mating; siblings/offspring/mates; verified health and DNA context; reports/export; saved breeding plans; multi-dog comparisons.

### C. Database and evidence trust (7)
Canonical breadth; pedigree-link completeness; photograph completeness; import/source provenance; evidence verified by a human; duplicate resolution; pedigree integrity (cycles/sex/date/identity).

### D. Members/kennels (8)
Email registration/reset; dashboard navigation; ownership claims and kennel roles; dog/photo/health/doc submissions; review status/evidence requests; payment entitlement correctness; research engagement/retention; privacy, consent and staff-account separation.

### E. Admin/moderation (9)
Super Admin workspace; searchable queues; warnings/second reviewer; dispute resolution; role boundaries; direct edit approval safeguards; merge dogs and audit/redirect/photo preservation; audit immutability; moderator navigation and productivity.

### F. Engineering/operations (8)
Security and authentication; response latency; production reliability; committed update freshness; relevant automated/real-browser coverage; local Postgres/R2 backup and restore drill; SEO; media delivery/integrity.

**No averaging away a failure:** The overall target of 9+ is not satisfied unless **each of the six categories and each critical subcategory** (publication authority, pedigree integrity, security, duplicate preservation, member privacy, backup recoverability, approval freshness) scores >=9.0 with supporting evidence.

## Measurable 9+ acceptance gates

| Area | Required observable evidence |
|---|---|
| Public and dashboard UX | Real-device task walkthroughs for iPhone Safari and desktop, 320/360/390/430/768/1024/1440 widths, dark/light, keyboard, scrolling, focus and zero severe WCAG findings |
| Research correctness | Repeated ancestors, cycles, missing parents, COI, virtual mating, reverse pedigree, merges and public/private ancestry verified using known test fixtures |
| Publication | Member drafts remain private; moderator clean approvals publish on next GET; high-risk overrides require independent review; sensitive live edits explicitly governed |
| Duplicate/identity | One real dog → one canonical row; merge review/confirmation; both image sets retained; child/parent links, history and redirects preserved; no unsanctioned merges |
| Trust and coverage | Report raw dog count, ancestor-link %, displayable image %, verified-with-evidence %, duplicates and integrity exceptions separately; show numerator and denominator |
| Member controls | Test separate anonymous/member/kennel viewer/editor/owner/moderator/senior/superuser identities with both permitted and forbidden actions |
| Reliability | No reproducible 5xx or Try Again navigation failures in normal journeys; production health and cross-browser smoke pass at deployed SHA; distinguish skipped/flaky checks |
| Speed | Measure p75 Core Web Vitals LCP <=2.5s, INP <=200ms, CLS <=0.1, plus authenticated and uncached dog/search/pedigree p95, cold/warm network and concurrency |
| Recoverability | Fresh Oracle-local DB backup and actual restore drill, R2 media sample verification, documented restore objective and no legacy hosted database writes |
| Release evidence | Date, release SHA, tests run and browser screenshots; update this scorecard only after verification—not when code merely exists |

## Upgrade order

1. Protect sensitive canonical data changes, audit every approval and preserve immediate visibility only after authorization.
2. Improve evidence provenance and verification metrics without declaring imported records verified.
3. Improve ancestry traversal, saved research/comparisons, and report usefulness, reusing canonical dogs only.
4. Refine existing design and member/moderator task flows instead of wholesale redesign; keep mobile logo/spacing owner-approved.
5. Optimize profiled database and end-to-end response bottlenecks; monitor production reliability, photos, backups and slow journeys.

## Operating protocol for every future PR

- Identify which of the 54 subcategories changes and record its **before and after acceptance check**.
- Use the current code and production state, not stale memories or previous PR summaries.
- Retain Django, Oracle-local Postgres, Cloudflare private VPC edge and R2; no new systems/services or migrations unless truly required.
- Protect user roles, paid submissions, no preapproval publication, privacy, audit trail, existing slugs and source images.
- Use only necessary change-scoped tests first; broad CI when cross-cutting models/security/pedigree demand it.
- Measure and post results after deployment. Never claim "9+" based solely on style changes or green CI.
- Do not perform real dog merges or purge records without owner-confirmed specific identities.
- Keep a rolling "Remaining below 9" list until verified. Preserve this baseline when adding other rules: **merge overlapping rules, do not duplicate policy documents**.

## Current work ledger

- [x] Comparison adopted as the permanent product scorecard.
- [ ] All six categories measured >=9 with real production and authenticated evidence.
- [ ] Sensitive direct-pedigree-change governance at 9+.
- [ ] Database evidence-verification and photograph-coverage improvement (without fabricating records).
- [ ] Saved comparison/breeding research at 9+.
- [ ] Field-tested UX, admin productivity and research usability at 9+.
- [ ] Sustained response-time and production-reliability benchmarks at 9+.
