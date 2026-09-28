# Cane Corso Ancestry — Implementation Status

Updated: 28 September 2026

## Current state

The repository now has a working Django ancestry platform foundation, owner-style public/member UI, Bellissimo seed import, pedigree analysis, member/kennel workflows, and a full moderation/search-intelligence layer.

Current validation:

- Django migration/check/test CI: passing;
- Bellissimo seed dry-run validation: passing;
- Playwright desktop/mobile smoke screenshots: passing;
- 34 Django tests across pedigree, import, member, moderation, ownership, duplicate and dispute workflows.

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

### Browser/UI acceptance

- Playwright smoke workflow at 1440×1000 desktop and 390×844 mobile.
- Global horizontal-overflow checks on ordinary pages.
- Screenshot coverage includes:
  - homepage;
  - dog search/profile;
  - public pedigree;
  - member dashboard;
  - My Pedigrees/private pedigree;
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

## Next major phase

### Advanced pedigree analysis

- Dedicated ancestor-contribution reporting.
- Rich linebreeding path visualization.
- Printable/exportable pedigree.
- Pedigree revision keys and analysis caching.
- Performance testing on dense 8–10 generation pedigrees.
- Better mobile analysis summaries for very deep pedigrees.

### Production phase after analysis

- Select/configure deployment host.
- Configure production PostgreSQL.
- Configure object storage for dog photos/evidence.
- Configure `canecorsoancestry.com` DNS.
- Backups.
- Production email provider.
- Security/permission audit.
- SEO/structured metadata.
- Monitoring/error reporting.

## Release principle

Do not add payment or paid-registration workflows merely because a Payments card exists in the supplied member mockup. Commercial features require a separately confirmed business model.

## Acceptance baseline

Every substantial visual change must continue to be compared against:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Every data change must preserve one canonical real-dog record and the relationships attached to it.
