# Cane Corso Ancestry — Implementation Status

Updated: 28 September 2026

## Current state

The repository now has a working Django ancestry platform foundation, owner-style public/member UI, Bellissimo seed import, pedigree analysis, member contribution workflows, kennel ownership workflows, litter management, document controls, and an internal moderation/verification layer.

Current validation:

- Django migration/check/test CI: passing;
- Bellissimo seed dry-run validation: passing;
- Playwright desktop/mobile smoke screenshots: passing;
- 25 Django tests, including the current member/kennel workflow phase.

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
- Unlinked kennel profiles expose a moderated ownership-claim entry point.

### Pedigree intelligence

- 4 / 6 / 8 / 10 generation pedigree views.
- Public-only pedigree traversal on public pages.
- Repeated ancestor highlighting.
- Common ancestor detection.
- Cycle-safe traversal.
- Wright-style inbreeding coefficient calculation.
- Virtual mating with projected COI.
- Member pedigree view can include private kennel records without exposing them publicly.
- Short tests covering repeated ancestors, half siblings and a known 12.5% half-sibling pairing.

### Member contribution tools

- Custom member login/dashboard.
- Kennel-role membership model with owner/editor/contributor roles.
- Submit a new dog for review.
- Submit corrections to an existing kennel dog.
- Submit dog photos.
- Submit pedigree/health/DNA/external-registration documents.
- Owner/editor kennel profile changes through review.
- Submission status/history.
- Notifications.
- Account/password flow.
- Contributions stay moderated instead of silently overwriting canonical pedigree data.

### Member / kennel workflow phase — complete

- Dedicated **My Pedigrees** workspace.
- Private member pedigree explorer for kennel records.
- Dedicated **My Litters** workspace.
- Owner/editor litter-create workflow through moderation.
- Owner/editor litter-edit workflow through moderation.
- Dog submissions/corrections can connect a dog to a same-kennel litter.
- Canonical validation prevents a dog being assigned to a litter from another kennel.
- Kennel claiming for genuinely unlinked kennels.
- Kennel claims require moderator approval before owner membership is granted.
- Already-linked kennels cannot be taken over through the public claim flow.
- Richer My Documents workspace with type and visibility filters.
- Moderated public/private document visibility requests.
- Optional email notification delivery for review decisions.
- SMTP/email delivery is environment-configurable and disabled by default.
- In-app notifications remain available regardless of email configuration.

### Moderation/data integrity

- Moderator review queue.
- Approve/reject submission workflow with reviewer notes.
- Approved new dogs and litters remain private until separately published.
- Field/source-level verification events.
- Overall dog verification updates.
- Safe atomic dog merge service.
- Sire/dam/offspring/litter relationships repointed before duplicate retirement.
- Aliases, external keys, registrations, titles, photos, health records, sources, documents, submissions and verification events reconciled during merge.
- Previous merge history preserved.
- Retired dog slugs redirect to the canonical record.
- Conservative duplicate suggestions based on normalized names and shared external registrations.
- No automatic merging from duplicate suggestions.

### Browser/UI acceptance

- Playwright smoke workflow at 1440×1000 desktop and 390×844 mobile.
- Global horizontal-overflow checks on normal pages.
- Screenshot coverage includes:
  - homepage;
  - dog search/profile;
  - public pedigree;
  - member dashboard;
  - My Pedigrees;
  - private member pedigree;
  - My Litters;
  - My Documents;
  - moderation queue;
  - dog submission form;
  - unlinked kennel claim entry/form.
- Actual screenshot artifacts reviewed against both owner reference images.
- UI review notes saved at `docs/UI_REVIEW.md`.

## Known visual/media gap

The imported ancestry seed contains pedigree/identity data but does not provide approved production dog image files in this Django media store.

Current placeholders are intentional. Do not fill a specific dog's profile with unrelated photography.

Approved photos can enter through the member photo submission/review workflow.

## Next major phase

### Moderation/search intelligence

- PostgreSQL trigram/fuzzy duplicate discovery for large datasets.
- Stronger duplicate confidence/explanation model.
- More granular dispute/correction cases.
- Before/after change diff presentation for moderators.
- Bulk moderation actions where safe.
- Better review queue filtering/prioritisation.
- Audit views for verification, merges and corrections.

### Later pedigree-analysis phase

- Dedicated ancestor-contribution reporting.
- Richer linebreeding path visualization.
- Printable/exportable pedigree.
- Analysis caching/revision keys for large pedigrees.
- Performance testing on dense 8–10 generation pedigrees.

### Production phase

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
