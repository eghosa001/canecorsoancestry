# Cane Corso Ancestry — Project Plan

## Product definition

Cane Corso Ancestry is a dedicated Cane Corso pedigree and ancestry platform. It is separate from Bellissimo Geni, while verified Bellissimo ancestry can be imported as one trusted source dataset.

The platform is an ancestry/pedigree database, not an official registration authority. External registration numbers and their issuing organizations can be stored and displayed.

## Owner-approved design direction

The two supplied WhatsApp mockups are the authoritative visual baseline for the project and must be retained in the repository under `docs/design-reference/`.

They define two major experiences:

- **Public ancestry/pedigree experience** — search, dog identity and multi-generation pedigree exploration.
- **Member/owner dashboard** — My Dogs, Pedigrees, Litters, Kennel, Health & DNA, Documents and account tools.

Implementation must preserve the design intent visible in those references:

- near-black/charcoal surfaces;
- restrained gold accents;
- warm ivory/off-white typography;
- premium Cane Corso photography;
- strong editorial/display typography;
- clear pedigree hierarchy;
- generous spacing;
- polished but serious breeder/pedigree character;
- desktop pedigree views with room to breathe;
- mobile layouts that restructure the tree rather than shrinking it into unreadable cards.

These mockups are requirements, not disposable inspiration. Do not replace them with a generic SaaS theme or a Bellissimo-specific kennel theme unless the owner explicitly changes the brief.

## Technology

The owner prefers Python/Django.

Primary stack:

- **Python**
- **Django**
- **PostgreSQL**
- Django templates for the core server-rendered experience
- HTMX and small targeted JavaScript/Alpine.js where progressive interaction improves UX
- Django REST Framework only where an API materially helps
- object storage for production dog images and evidence/documents
- Playwright for browser-level responsive/regression tests

Django Admin can support the first internal moderation workflows, but regular breeders/members should use the custom owner-approved dashboard rather than raw Django Admin.

## Core data model

A real dog must have exactly one canonical record.

Primary models:

- Dog
- DogAlias
- Registration
- Kennel
- KennelMembership
- Litter
- HealthRecord
- DNATest
- Title
- DogImage
- Document
- Source
- VerificationEvent
- Submission
- MergeHistory
- AuditLog
- User/Profile

Each Dog can point to canonical `sire` and `dam` Dog records.

Repeated ancestors caused by linebreeding should appear multiple times in a rendered pedigree while still resolving to the same canonical Dog record.

## Duplicate safety

Duplicate dogs must never be fixed by blindly deleting one record.

A safe merge must:

1. choose a canonical record;
2. repoint every sire/dam relationship;
3. preserve all offspring and litter links;
4. move registrations, aliases, photos, health/DNA records, documents and sources;
5. preserve redirects/aliases from retired identifiers;
6. record the merge in immutable audit history.

## Public product

- Home
- Global dog search
- Advanced dog search
- Dog profiles
- Interactive pedigree explorer
- Kennel directory and kennel profiles
- Litter profiles
- Offspring and sibling views
- Health/DNA presentation
- Pedigree analysis
- Virtual mating
- Source and verification visibility

## Member product

- My Dogs
- My Pedigrees
- My Litters
- My Kennel
- Health & DNA
- Documents
- Submission/correction history
- Notifications
- Account settings

## Moderation/admin

- submission review queue
- duplicate detection
- safe record merge
- evidence/document review
- kennel verification
- publication controls
- immutable audit trail
- disputed-data/correction handling

## Search and pedigree intelligence

Search should support:

- dog name and aliases
- kennel
- breeder
- registration number
- partial/fuzzy name matching
- sex
- date/birth range
- colour
- country
- health/DNA filters
- verification state

Pedigree tools should support:

- 4/6/8/10-generation views
- repeated-ancestor highlighting
- common-ancestor detection
- sibling/half-sibling discovery
- offspring
- ancestor contribution
- COI calculation
- virtual mating
- cached analysis tied to pedigree revision

## Verification model

Avoid a single vague verified flag.

Suggested states:

- Community submitted
- Source attached
- Identity reviewed
- Pedigree reviewed
- Health/DNA verified

Kennels may separately receive a **Verified Kennel** status.

Verification should always describe what was reviewed and, where possible, cite the supporting source.

## Bellissimo Geni integration

Bellissimo remains independent.

Initial data flow:

`Bellissimo verified pedigree data → import/normalisation → Cane Corso Ancestry canonical database`

Do not make the new site depend on Bellissimo's static files or Cloudflare KV at runtime.

Later, Bellissimo may consume a stable public ancestry API from Cane Corso Ancestry if useful.

## Delivery phases

### Phase 1 — Foundation

- Django project scaffold
- PostgreSQL configuration
- environment/settings structure
- owner-approved design tokens
- authentication
- core Dog/Kennel/Registration models
- seed/import tooling
- targeted test baseline

### Phase 2 — Canonical ancestry graph

- sire/dam relationships
- aliases
- litters
- source/provenance records
- duplicate detection
- safe merge service
- Bellissimo import pipeline

### Phase 3 — Public experience

- homepage matching the supplied public reference
- dog search
- dog profile
- pedigree explorer
- kennel and litter pages
- responsive mobile behaviour

### Phase 4 — Pedigree intelligence

- repeated ancestors
- common ancestors
- siblings/offspring
- COI
- virtual mating
- analysis caching

### Phase 5 — Member dashboard

- custom dashboard matching the supplied member reference
- dog/kennel management
- health and DNA records
- documents
- submissions/corrections
- notifications

### Phase 6 — Verification and moderation

- review queues
- evidence review
- merge tooling
- provenance display
- audit history

### Phase 7 — Production hardening

- permissions/authorization checks
- Playwright desktop/mobile coverage
- accessibility
- image-quality validation
- backups
- performance/caching
- SEO/structured data
- deployment and custom domain

## First-release exclusions

Do not prioritize payments or paid registration workflows in the first release. Build pedigree integrity, search, ancestry exploration, kennel participation and verification first.

## Definition of done for the initial product

A user can search a Cane Corso, open its profile, move through ancestors, siblings and offspring, inspect pedigree sources and health data, identify repeated ancestors, explore the associated kennel and run a virtual mating calculation without losing navigation context.

The supplied design references remain visible in the repository so future implementation and review can always be checked against the owner's approved direction.
