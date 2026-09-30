# Data ingestion policy

Cane Corso Ancestry is a canonical pedigree research database. Record count is never a reason to weaken provenance or identity controls.

## Admission rules

A bulk source must have a clear owner/source URL, stable source identifiers, and enough pedigree context to review identity. Do not scrape or import a dataset merely because it is publicly reachable. Respect source terms, copyright, privacy, and access controls.

Before any import:

1. Keep an immutable source snapshot or checksum.
2. Run `python manage.py validate_pedigree_dataset <file>`.
3. Resolve all hard validation failures before writing data.
4. Treat same-name warnings as identity-review work, not automatic merges.
5. Use a stable namespace for external source IDs.
6. Keep new records private unless the source has been explicitly approved for public use.
7. Preserve source URLs/raw payload through `DogSource`.
8. Never overwrite a conflicting external registration.
9. Run `python manage.py audit_pedigree_data --fail-on-critical` after import.
10. Review the staff Data Health dashboard after every large ingestion.

## Canonical identity

One real dog should map to one canonical `Dog`. When a later source matches an existing dog, attach provenance or submit a correction. Do not create a parallel record merely because spelling, punctuation, kennel formatting or transliteration differs.

The indexed `normalized_name`, external registration constraints, external keys, pedigree facts and moderator duplicate tools are identity signals. They do not authorize an automatic merge by themselves.

## Publication

Community submissions and unreviewed bulk records stay non-public. Publication is a moderation decision. Draft/private source records must remain private on import.

## Quality gates

Hard failures include:

- duplicate source IDs;
- duplicate external registration numbers within a dataset;
- references to missing parents;
- pedigree cycles;
- the same dog used as sire and dam;
- a female record used as sire or male record used as dam;
- a parent born on or after the child.

Warnings include same normalized names and incomplete demographic fields. Warnings require review but may be legitimate.

## Current canonical seed

`data/seeds/bellissimo-dogs.json` remains the controlled Bellissimo Geni seed. The production seed workflow validates the snapshot, imports idempotently, verifies expected public/private counts and runs the full integrity audit.
