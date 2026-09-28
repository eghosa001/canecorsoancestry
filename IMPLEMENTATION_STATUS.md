# Cane Corso Ancestry — Implementation Status

Updated: 28 September 2026

## Current state

The repository now has a production-deployed Django ancestry platform with owner-style public/member UI, Bellissimo seed data, advanced pedigree analysis, member/kennel workflows, moderation/search intelligence, Railway PostgreSQL and private object storage.

Current validation:

- Django migration/check/test CI: passing;
- Bellissimo seed dry-run validation: passing;
- Playwright desktop/mobile smoke screenshots: passing;
- 45 Django tests across pedigree, import, member, moderation, ownership, duplicate, dispute and production-surface workflows.

## Completed

### Product guardrails

- Pedigree/ancestry platform, **not a registry**.
- Django/Python architecture documented.
- Owner-approved public and member/dashboard reference images retained in full resolution under `docs/design-reference/`.
- Terminology, verification, duplicate-safety and canonical-dog rules documented.
- Half siblings are explicitly treated as siblings when they share either parent.

### Django foundation

- Django 5.2 project structure.
- PostgreSQL-ready database configuration with local SQLite fallback.
- Separate development/production settings.
- Accounts/profile app.
- Registry data app for canonical dog/kennel/litter/external-registration data.
- Pedigree analysis app.
- Migrations tracked in source control.
- Fast GitHub Actions checks for migration drift, Django checks and tests.

### Core ancestry data

- Canonical Dog records with sire/dam relationships.
- Kennels and kennel memberships.
- Litters.
- Aliases.
- External registration authorities and numbers.
- Dog images.
- Health records.
- Titles.
- Sources/provenance.
- Approved dog documents.
- External source keys used for safe imports.
- Evidence-scoped verification events.
- Member notifications.
- Submission/review records.
- Merge history and old-slug redirects.
- Dispute/review cases.
- Moderation audit events.

### Bellissimo seed/import

- Verified Bellissimo seed dataset retained in `data/seeds/`.
- Import management command.
- Import provenance support.
- CI validation of the complete seed.
- Shared ancestors stay canonical instead of being duplicated for each pedigree position.

### Public experience

- Dark charcoal / gold / warm ivory design derived from the owner's supplied references.
- Homepage with search, counts and feature navigation.
- Dog search with name, alias, bloodline, kennel and external-registration matching.
- Sex, country and kennel filtering.
- Structured dog profile.
- Parent navigation.
- External registration presentation.
- Health & DNA section.
- Titles.
- Public documents.
- Source/provenance section.
- Full and half sibling discovery.
- Offspring discovery.
- Kennel directory/profile.
- Litter pages.
- Old dog URLs redirect to the surviving canonical record after a merge.
- Logged-in users can open a moderated review/dispute case from a public dog profile.

### Pedigree intelligence

- 4 / 6 / 8 / 10 generation pedigree views.
- Public-only pedigree traversal on public pages.
- Repeated ancestor highlighting.
- Common ancestor detection.
- Cycle-safe traversal.
- Wright-style inbreeding coefficient calculation.
- Virtual mating with projected COI.
- Member pedigree view can include private kennel records without exposing them publicly.


### Advanced pedigree analysis phase — complete

- Dedicated ancestor-contribution reporting with expected pedigree-share percentages.
- Repeated ancestors combine contributions from every visible pedigree path.
- Rich linebreeding-path reporting shows the exact sire/dam route, generation and path contribution.
- Repeated paths are classified as sire-side concentration, dam-side concentration, or crossing both sire and dam lines.
- Shared bounded pedigree snapshots load parents in batches instead of occurrence-by-occurrence ORM traversal.
- Deep 8–10 generation analysis reuses the same bounded graph for the board, contributions and linebreeding analysis.
- Focused performance coverage enforces at most one parent query per generation for the 10-generation board path.
- Pedigree revision keys are derived from the visible ancestry graph and relevant canonical dog facts.
- Advanced analysis payloads are cached under the dog, depth, public/private scope and revision key, so canonical pedigree edits naturally move analysis to a new cache entry.
- Pedigree coverage reports known ancestry positions, unique ancestors, deepest known generation and per-generation completeness.
- Public pedigree CSV export is available for the selected generation depth.
- Member CSV export can include private kennel ancestry only when the signed-in member belongs to that dog's kennel.
- Browser-native printable pedigree/report layout is provided with a dedicated landscape print stylesheet.
- Public and member analysis summaries are responsive on mobile while the deep pedigree board remains intentionally horizontally scrollable.
- Analysis remains read-only and never changes canonical pedigree relationships.

### Member / kennel workflows

- Custom member login/dashboard.
- Kennel-role membership model with owner/editor/contributor roles.
- Submit dog/corrections/photos/documents through moderation.
- Dedicated My Pedigrees workspace.
- Private member pedigree explorer.
- Dedicated My Litters workspace.
- Moderated litter create/edit.
- Same-kennel litter validation.
- Moderated kennel ownership claiming for genuinely unlinked kennels.
- Richer My Documents workspace with type/visibility filters.
- Moderated public/private document visibility.
- In-app notifications.
- Optional SMTP email review notifications.
- My Review Cases workspace for dispute status and moderator resolution notes.

### Moderation / search intelligence phase — complete

- Priority levels for pending submissions: Low / Normal / High / Urgent.
- Moderator assignment and review-start tracking.
- Queue filtering by text, submission type, priority and assignment.
- Default queue ordering by highest priority, then oldest waiting item.
- Aging indicator for long-waiting submissions.
- Human-readable **before → after** diffs for correction, kennel, litter and document-visibility reviews.
- New-record submissions display proposed facts clearly.
- Safe bulk operations:
  - assign selected to current moderator;
  - unassign;
  - set priority;
  - bulk reject with mandatory reason.
- **Bulk approval is intentionally unavailable**.
- Member dispute/review cases for:
  - pedigree relationships;
  - dog identity;
  - health/DNA facts;
  - kennel/ownership facts;
  - possible duplicate dogs;
  - other evidence-based concerns.
- Dispute assignment, resolution and dismissal with required moderator notes.
- Opening a dispute never changes the canonical dog automatically.
- Searchable moderation audit history.
- Audit events recorded for:
  - approval;
  - rejection;
  - safe bulk changes;
  - canonical merges;
  - verification events;
  - dispute creation/update.
- PostgreSQL `pg_trgm` extension enabled conditionally in production migrations.
- Scalable moderator dog lookup using PostgreSQL trigram similarity.
- Portable local/SQLite fuzzy fallback for development/tests.
- Ranked duplicate matching with evidence from:
  - normalized/fuzzy name similarity;
  - external registrations;
  - sire;
  - dam;
  - date of birth;
  - kennel;
  - sex consistency.
- Duplicate matches include confidence level, score and explanation.
- High-signal database-wide duplicate suggestions remain suggestions only.
- All merges remain explicit moderator actions using the safe atomic merge service.
- Existing duplicate-match API aliases retained for backward compatibility.

### Production deployment — operational

- Dedicated Railway project: `Cane Corso Ancestry`.
- Production PostgreSQL service is online with a persistent volume.
- Production web service deploys from `eghosa001/canecorsoancestry` `main`.
- Railway deployment `fa258ef` is healthy and `/healthz/` returns HTTP 200.
- Static collection is part of the build/runtime path; 128 static files are present in the production image.
- Private S3-compatible object storage is wired through Django `default_storage`.
- Storage was verified through the live Django container with successful PUT / GET / DELETE of a temporary probe object.
- Bellissimo production seed import verified: 117 canonical records imported, 101 public and 16 draft.
- Production media/evidence does not depend on ephemeral web-container storage.
- Production security headers, HTTPS redirect, secure cookies, proxy-aware HTTPS handling and private-page noindex/no-store controls are enabled.
- Public SEO includes robots.txt, sitemap.xml, canonical/Open Graph metadata and JSON-LD.
- Request IDs and Railway health/runtime logging are active.
- Optional Sentry integration is code-ready and activates only when `SENTRY_DSN` is supplied.
- Resend SMTP configuration is code-ready; email notifications remain disabled until a Resend credential and sender-domain verification are connected.
- `canecorsoancestry.com` is attached to the Railway web service. Railway requires the apex DNS CNAME to `7i4x0mqk.up.railway.app`.
- Current Railway plan allows one custom domain per service, so `www` should redirect to the apex at the DNS/CDN layer instead of being attached as a second Railway custom domain.
- Daily / Weekly / Monthly PostgreSQL backup schedules were submitted to Railway, but Railway's API does not expose schedule state for verification; verify the Backups tab or `railway postgres pitr schedule list` before treating the schedule as audited.

### Browser/UI acceptance

- Playwright smoke workflow at 1440×1000 desktop and 390×844 mobile.
- Global horizontal-overflow checks on ordinary pages.
- Screenshot coverage includes:
  - homepage;
  - dog search/profile;
  - public pedigree on desktop and mobile, including advanced analysis;
  - member dashboard;
  - My Pedigrees/private pedigree on desktop and mobile, including advanced analysis;
  - My Litters;
  - My Documents;
  - My Review Cases;
  - moderation review queue;
  - moderation audit history;
  - dog submission;
  - kennel claiming.
- Moderation screenshots contain real seeded pending corrections/disputes rather than empty-only states.
- Final moderation review confirmed the bulk action bar does not cover merge or verification controls.

## Known visual/media gap

The imported ancestry seed contains pedigree/identity data but does not provide approved production dog image files in this Django media store.

Current placeholders are intentional. Do not fill a specific dog's profile with unrelated photography.

Approved photos can enter through the member photo submission/review workflow.

## Remaining external activation

The application and Railway infrastructure are operational. The remaining items require access to external provider accounts rather than repository code:

- create the apex DNS CNAME `canecorsoancestry.com → 7i4x0mqk.up.railway.app` and use the DNS/CDN provider to redirect `www` to the apex;
- connect Resend, verify `canecorsoancestry.com`, supply `EMAIL_HOST_PASSWORD`, then enable `ANCESTRY_EMAIL_NOTIFICATIONS=1`;
- optionally supply a Sentry DSN to activate application error reporting;
- verify Railway's Daily / Weekly / Monthly backup schedule through the dashboard or Railway CLI because schedule state is not readable through the current API.

## Release principle

Do not add payment or paid-registration workflows merely because a Payments card exists in the supplied member mockup. Commercial features require a separately confirmed business model.

## Acceptance baseline

Every substantial visual change must continue to be compared against:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Every data change must preserve one canonical real-dog record and the relationships attached to it.
