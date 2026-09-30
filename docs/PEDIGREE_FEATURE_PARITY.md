# Pedigree Feature Parity Baseline

Updated: 30 September 2026

This document defines the core ancestry/pedigree capability expected from Cane Corso Ancestry. It is informed by established pedigree database patterns while preserving this project's rule that it is an ancestry/research platform, not a registration authority.

## Canonical relationship graph

- One canonical record per real dog.
- Sire and dam links are the source of truth.
- Linking a dog to a sire or dam automatically updates the parent's offspring view.
- Full siblings and half siblings are derived automatically from shared parents.
- Mates are derived automatically from shared offspring.
- Reverse pedigree follows descendants across multiple generations.
- Duplicate merges repoint parent, offspring, litter and attached records safely.
- Parent cycles are rejected or safely detected during analysis.

## Pedigree intelligence

- 4, 6, 8 and 10 generation ancestry views.
- Repeated ancestor detection and path highlighting.
- Wright-style coefficient of inbreeding (COI).
- Ancestor loss across known pedigree positions.
- Pedigree coverage/completeness.
- Ancestor contribution / blood-share analysis.
- Linebreeding path analysis.
- Common-ancestor analysis.
- Virtual mating with projected COI.
- Reverse pedigree / descendant exploration.
- CSV export and print-friendly pedigree reports.

## Family and health intelligence

- Parent profiles.
- Full and half siblings.
- Offspring.
- Mates and offspring grouped from canonical links.
- Direct-relative health overview for parents, siblings and offspring.
- Health/DNA records retain verification state.

## Identity, integrity and moderation

- Public member signup/sign-in.
- Member dog submissions remain non-public until admin approval.
- Corrections, photos and documents go through moderation.
- Exact registration collisions are blocked before duplicate dog creation.
- Strong likely duplicates are blocked/prevented and moderator duplicate intelligence remains available.
- Safe canonical merge preserves relationships, redirects and attached records.
- Disputes and moderation audit trail.
- Evidence/provenance and verification events.

## Kennels / breeder brands

- Public kennel profiles and kennel memberships.
- New kennel profiles are moderator-approved.
- Existing and pending kennel/brand names are protected against duplicate creation.
- Canonical slug uniqueness provides a database-level collision guard.
- Only one ownership claim may be under review for a kennel at a time.
- Approved kennel creators become the owner of the canonical kennel profile.
- Existing unlinked kennels can be claimed through moderated ownership review.

## Search and scale

- Search by dog name, alias, bloodline, kennel and external registration.
- Exact name/alias/registration search.
- Sex, country and kennel filtering.
- Results are paginated rather than rendering the entire dog database.
- Homepage popularity is based on search-originated dog profile visits.
- Statistics include popular sires, popular dams and kennels by public records.
- PostgreSQL trigram-assisted moderator duplicate search with portable fallback.

## Litters

- Canonical litter records.
- Sire and dam links.
- Offspring links.
- Moderated litter creation and correction.
- Litter/kennel consistency checks.
- Parent/offspring relationships automatically feed sibling, mate and reverse-pedigree intelligence.

## Optional product extensions

These are not required for pedigree integrity and should only be added when the owner wants the corresponding product direction:

- Forums or public comments.
- Classified adverts.
- Paid subscriptions.
- Private messaging.
- Breeder advertising/marketplace tools.
- Favourite lists and private notes.
- Planned-litter marketing/availability listings.

The core pedigree graph, analysis, moderation, identity protection, health relationships and scalable search are the production baseline.
