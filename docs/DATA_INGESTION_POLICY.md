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

## Current trusted source snapshots

- `data/seeds/bellissimo-dogs.json`: 117 canonical Bellissimo pedigree source records, of which 101 are public and 16 remain draft/private.
- `data/seeds/bellissimo-puppies.json`: two additional kennel-verified young-dog records from the owner's Bellissimo Geni data, imported only as pedigree facts with breeder-source provenance. Sales/availability fields are retained only in the raw provenance payload and are not part of the ancestry site's public data model.

- CaneCorsoPedigree.com archive snapshot (Google Drive file id \`1WFeLJjAi728rhzF4z9PJ36QNFFp2qnxs\`): scraped 2026-09-15, SHA-256 \`4acfb0e046ada9818719cafa360829a8aba96f3fcb16c630d675dffe3c76669b\`. The production importer selects the 13,416 source records whose DOB begins with 2020-2026 and recursively includes 19,721 usable named ancestors, for 33,137 source-linked records. Five referenced source rows whose name is literally `Unknown` are deliberately excluded. Imported images are not republished by this workflow. Unsafe or conflicting parent links are skipped rather than overwriting canonical relationships.

The production seed workflows import approved sources idempotently, verify expected counts and relationships, and run the full integrity audit afterward.
