# Owner Requirements

This file records the requirements that must survive future implementation and redesign work.

## Confirmed project identity

- Public project name: **Cane Corso Ancestry**.
- This is a **pedigree and ancestry website, not a dog registry**.
- Python/Django is the preferred backend technology.
- No custom domain has been purchased or configured; use the current Cloudflare `workers.dev` public endpoint unless the owner explicitly changes this.
- The two supplied design mockups in `docs/design-reference/` are the owner-approved visual baseline and must remain in the repository.

## Terminology rules

The product must not imply that Cane Corso Ancestry is an official registration authority.

Use:
- **Add dog**
- **Submit dog**
- **Submit pedigree**
- **Database ID / CCA ID**
- **External registration**
- **Registration authority**
- **Registration number**

Avoid using **Register a Dog**, **Registered Dog**, or similar language when it would imply that Cane Corso Ancestry itself issues registrations.

A dog may display one or more real registration numbers from external authorities. Those numbers belong to the issuing authority, not Cane Corso Ancestry.

A **verified** badge means the relevant identity, pedigree, health result, kennel, or document was reviewed against supporting evidence. It does not mean that Cane Corso Ancestry registered the dog.

## Owner-approved visual scope

The public reference image establishes the intended visual language and page family:

1. Homepage
2. Dog search/results
3. Dog profile
4. Interactive pedigree tree
5. Pedigree/inbreeding analysis
6. Health and DNA records
7. Litter page
8. Kennel profile
9. Virtual mating
10. Moderation/admin dashboard

The member reference establishes the signed-in breeder/member experience:

- My Profile
- Dashboard
- My Dogs
- My Pedigrees
- My Litters
- My Kennel
- Health & DNA
- My Documents
- Notifications
- Account Settings

The visual direction is dark charcoal/near-black with restrained gold, warm ivory typography, strong Cane Corso photography, compact data-rich cards, and an editorial pedigree feel.

The mockups are design references, not permission to copy Bellissimo Geni branding into the public Cane Corso Ancestry identity.

## Product behavior

### Canonical dogs

One real dog must map to one canonical database record.

A linebred pedigree may display the same ancestor in several pedigree positions, but those positions must resolve to the same canonical dog.

### Canonical litters

A real birth event maps to one litter. When sire, dam and date of birth are all known, **the same sire + same dam + same date of birth is one canonical litter**, regardless of puppy count or submission code. Moderation must block creation of a second litter for the same parent pair and birth date and direct reviewers to the existing litter.

### Relationships

Parent relationships are stored once as sire/dam links.

From those links the website should derive automatically:

- ancestors;
- offspring;
- full siblings;
- half siblings;
- repeated ancestors;
- common ancestors;
- pedigree paths.

### Public dog discovery

Public dog browse, typed search and autocomplete/suggestion lists show photographed dogs only. A displayable photo may be a managed upload or a trusted imported source image that passes the site's image-source validation. Image-less pedigree records may remain directly addressable and may appear inside pedigrees/relationships, but must not surface as normal public listing cards or search suggestions.

### Duplicate handling

Never fix duplicate dogs by deleting one record before relationships are reconciled.

A merge must preserve and repoint:

- sire/dam references;
- offspring;
- litters;
- aliases;
- external registrations;
- photos;
- health/DNA records;
- documents;
- sources;
- kennel relationships;
- audit history.

### Provenance

Important pedigree and health claims should carry source/provenance information where available.

Missing facts stay missing. Do not invent:
- parents;
- registration numbers;
- dates;
- colours;
- health results;
- titles;
- breeder/owner facts;
- kennel details.

## Account and authority separation

Member identities and moderation/administration identities are permanently separate accounts.

- A **Member** account represents the kennel/member side of the platform. It may hold kennel Owner, Editor, or Contributor membership and may submit/manage its own dogs, litters, payments, documents, evidence, health/DNA records, disputes, and profile data.
- A Member account must never receive Moderator, Senior Moderator, or Super Admin authority. A kennel/member username or email cannot be promoted into staff authority.
- A person who is both a breeder/member and part of the moderation team must use **two different accounts and two different login identities**: one Member account and one dedicated staff account.
- A **Moderator** is a dedicated non-member staff identity. It may review ordinary submissions, request evidence, handle disputes, and record verification events. It has no member/kennel ownership tools and no Django Admin access.
- A **Senior Moderator** is a dedicated non-member staff identity. It has Moderator abilities plus flagged/high-risk decisions, overrides, duplicate merges, and second approvals. It cannot create staff accounts, change system verification rules, or use Django Admin.
- A **Super Admin** is a dedicated Django superuser identity. It can manage staff accounts/roles, verification rules, protected-record locks, and Django Admin in addition to moderation authority.
- Django `is_staff` alone must never grant moderation authority. Moderation authority comes only from an explicit dedicated staff-role assignment.
- Django Admin is reserved for Super Admin identities only.
- Staff identities may not later acquire kennel membership or submit member-owned records. Member identities may not later acquire moderation authority.
- Suspending a staff role must not convert that account into a Member account.

These are authorization invariants, not UI conventions, and must be enforced server-side as well as reflected in navigation and dashboards.

## Payments

The owner has confirmed a Paystack-backed paid submission model. Payment buys a submission/review slot; it never publishes or verifies a dog automatically.

Current packages:

- **₦500** — one dog;
- **₦1,500** — 2–6 dogs from the same verified kennel;
- **₦1,000** — one genuine litter plus the puppies belonging to that litter.

Only approved kennel owners/editors may purchase submission packages. Every paid dog or litter remains private/pending until the normal verification and administrator moderation flow approves it. Cane Corso Ancestry remains a pedigree/ancestry platform and must not describe these charges as official dog registration fees.

## Design-reference files

Do not remove or downscale:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

They are permanent acceptance references for future UI reviews.


## Production acceptance gates

Changes affecting identity, payments, public discovery, moderation, authentication, media, or production configuration must stay covered by change-scoped automated tests. Release validation must include SQLite and PostgreSQL, production security/settings checks, live public-route smoke, and post-deploy Chromium/Firefox/WebKit plus serious/critical accessibility checks. Production data health must fail on canonical-litter duplicates, case-insensitive kennel duplicates, staff/member identity overlap, or litter-member parent/date conflicts. Password recovery is not considered production-ready while outbound account email is disabled.
