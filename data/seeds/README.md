# Seed data

`bellissimo-dogs.json` is a versioned snapshot of the public, verified pedigree data from the user's Bellissimo Geni repository.

Source repository: `eghosa001/bellissimo-geni-cane-corso`  
Source path: `data/dogs.json`  
Source blob: `58e6251733aaefbb2bdea46525ccc5b89932cc40`  
Snapshot date: 2026-09-28

The source contains 117 canonical dog records. Sixteen records have `publishStatus: "draft"`; the importer keeps those records private. Source IDs are stored as external keys so re-importing does not create duplicate ancestors.

Image paths in the source payload are preserved as provenance only. Media files are not copied by this seed import.
