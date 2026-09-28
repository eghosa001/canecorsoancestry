# Owner Requirements

This file records the requirements that must survive future implementation and redesign work.

## Confirmed project identity

- Public project name/domain: **Cane Corso Ancestry / canecorsoancestry.com**.
- This is a **pedigree and ancestry website, not a dog registry**.
- Python/Django is the preferred backend technology.
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

## Payments

The member mockup contains a Payments panel. Treat that as part of the supplied visual reference only.

Payments, paid registration, or charging for dog registration are **not part of the initial product scope** unless the owner separately confirms the commercial model.

## Design-reference files

Do not remove or downscale:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

They are permanent acceptance references for future UI reviews.
