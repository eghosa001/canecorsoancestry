# Cane Corso Ancestry — Implementation Status

Updated: 28 September 2026

## Current state

The repository now has a working Django foundation and the first owner-style ancestry experience. The current main branch passes the Django CI workflow.

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
- Initial migrations.
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
- External source keys used for safe imports.

### Bellissimo seed/import
- Verified Bellissimo seed dataset retained in `data/seeds/`.
- Import management command.
- Import provenance support.
- CI validation of the complete seed.
- Shared ancestors stay canonical instead of being duplicated for each pedigree position.

### Public experience — first pass
- Dark charcoal / gold / warm ivory design derived from the owner's supplied references.
- Homepage with search, counts and feature navigation.
- Dog search with name, alias, bloodline, kennel and external-registration matching.
- Sex, country and kennel filtering.
- Structured dog profile.
- Parent navigation.
- External registration presentation.
- Health & DNA section.
- Titles.
- Source/provenance section.
- Full and half sibling discovery.
- Offspring discovery.
- Kennel directory/profile.
- Litter pages.

### Pedigree intelligence — first pass
- 4 / 6 / 8 / 10 generation pedigree views.
- Public-only pedigree traversal on public pages.
- Repeated ancestor highlighting.
- Common ancestor detection.
- Cycle-safe traversal.
- Wright-style inbreeding coefficient calculation.
- Virtual mating with projected COI.
- Short tests covering repeated ancestors, half siblings and a known 12.5% half-sibling pairing.

### Member experience — first pass
- Custom member login.
- Custom member dashboard rather than exposing Django Admin as the normal member interface.
- Linked kennel summary.
- My Dogs.
- My Litters.
- Health/DNA summary.
- Account/password flow.
- Responsive member layout based on the supplied dashboard reference.

## Still to build

### Data integrity / moderation
- Safe canonical duplicate-merge service that atomically repoints relationships and attached data.
- Merge history model/workflow.
- Submission/correction workflow.
- Moderator review queues.
- Field/source-level verification events.
- Dispute/correction handling.
- Better duplicate suggestions/fuzzy matching.

### Member tools
- Add/submit dog form.
- Submit pedigree/correction forms.
- Dog image/document uploads.
- My Pedigrees workspace.
- My Documents workspace.
- Notifications.
- Full kennel editing/claiming flow.
- Role-specific owner/editor/contributor permissions.

### Pedigree analysis
- Dedicated ancestor-contribution reporting.
- Richer linebreeding paths.
- Printable/exportable pedigree.
- Analysis caching/revision keys for large pedigrees.
- Performance testing on dense 8–10 generation pedigrees.

### Visual/UX refinement
- Use actual production dog imagery as records gain approved media.
- Browser screenshot regression tests against the supplied references.
- Mobile pedigree interaction polish.
- Accessibility review.
- Final typography/icon/spacing pass.
- Empty/error/loading states across all member actions.

### Production
- Select/configure deployment host.
- Configure PostgreSQL production database.
- Configure object storage for dog photos and evidence.
- Domain/DNS for `canecorsoancestry.com`.
- Backups.
- Email delivery for account flows/notifications.
- Security/permission audit.
- SEO and structured metadata.
- Production monitoring.

## Release principle

Do not add payment or paid-registration workflows merely because a Payments card exists in the supplied member mockup. Commercial features require a separately confirmed business model.

## Acceptance baseline

Every future visual review should compare the implementation against:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Every future data change should preserve one canonical real-dog record and the relationships attached to it.
