# Production quality standards

The owner-approved comparative baseline and 54-subcategory 9+ assessment are in `docs/COMPARATIVE_QUALITY_9PLUS.md`. Any claim that the site has reached 9+ must meet that benchmark as well as the technical gates below.

These are acceptance criteria, not achieved scores. A green workflow is not proof of a 9/10 user experience.

## Performance and reliability

- Measure real-user Core Web Vitals (75th percentile): LCP <= 2.5s, INP <= 200ms, CLS <= 0.1; do not represent CI navigation timings as LCP.
- Measure warm/cold, HIT/MISS/BYPASS, mobile/desktop separately. Report query counts and DB time along with origin/edge response time.
- Target uncached dog-profile p95 <= 1.5s with 8 concurrent clients. Currently fail above 5.0s using nearest-rank p95 across 24 dynamic requests as a regression guard while optimizing. This is not a performance-quality target.
- Target health p95 <= 1s, currently fail above 2s.
- Audit production-like PostgreSQL query plans for dog-profile, kennel, search, and pedigree routes. Prevent N+1 regressions.
- Deliver appropriately sized image variants, maintain intrinsic dimensions, and check CSS/font render blocking before claiming frontend optimization.
- Verify cold starts, origin availability, edge cache key isolation, and private response protection.
- Exercise uploads, email verification/password reset delivery, Paystack sandbox, member and admin moderation flows end to end; GET 200 alone is not sufficient.

## UI and accessibility

- Cover at least 320, 360, 390, 430, 768, 1024, and 1440px widths; use WebKit for iPhone-safe-area behavior.
- Check overflow, clipping, tap size, scrolling dropdowns, focus, labels, reduced motion, and dark/light themes on every relevant page type.
- Preserve the owner-approved mobile logo spacing and premium design. No arbitrary circular logo or excessive vertical whitespace.
- Consolidate CSS cascade and duplicate rules instead of adding new `!important` overrides with every UI fix.

## Trust, SEO and completeness

- A source attachment is not an independent verification; never mark imported records verified without evidence and admin review.
- Never duplicate dogs, kennels or litters to improve coverage scores. Preserve valuable ancestry records even when photo-less.
- Track total public dogs, imaged public dogs, verified-source dogs and pedigree-linked dogs as separate metrics.
- Test canonical tags, sitemap, structured data, real search links, accessibility and recovery pages.

## Release and score policy

- Run only relevant tests first and full cross-cutting checks when pedigree, models, CSS, deployment or security change.
- Benchmark against production evidence after deploying. Only increase category scores once repeat tests justify it.
- Investigate skipped and flaky checks. No blanket 9+/10 claims based on CI alone.
