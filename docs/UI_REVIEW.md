# UI Review

Last reviewed: 28 September 2026

## Automated browser coverage

The Playwright smoke workflow renders the live Django application after migrations and a Bellissimo seed import.

Acceptance viewports:

- desktop: 1440 × 1000
- mobile: 390 × 844

The workflow checks for global horizontal overflow and captures screenshots for:

- homepage;
- dog search;
- dog profile;
- public pedigree index/detail;
- member dashboard;
- My Pedigrees;
- private member pedigree detail;
- My Litters;
- My Documents;
- moderation/review queue;
- submit-dog form;
- claimable kennel profile;
- kennel ownership claim form.

The screenshot artifact is uploaded as `ui-smoke-screenshots`.

## Comparison with the owner references

The implementation follows the supplied references in:

- near-black/charcoal surfaces;
- restrained gold;
- warm ivory typography;
- strong serif headings;
- dense pedigree/data cards;
- prominent search;
- multi-generation pedigree browsing;
- left-rail member dashboard on desktop;
- kennel/dog/litter/health/document groupings;
- moderator review and verification areas.

The new My Pedigrees, My Litters and My Documents screens retain the same visual system rather than introducing a separate generic dashboard style.

## Current media limitation

The imported Bellissimo ancestry seed contains pedigree/identity data but does not provide approved production dog image files to this Django media store.

For that reason, current automated screenshots display the CCA placeholder in many photo regions.

Do **not** fabricate a specific dog's photograph or reuse an unrelated dog image merely to fill a card. Approved photos can enter through the member photo workflow, be reviewed, and then attach to the canonical dog.

The homepage hero should receive an approved high-resolution Cane Corso image once the owner supplies or approves production media.

## Mobile

The mobile smoke test confirms that ordinary pages and the member workspaces do not create global horizontal overflow.

The pedigree board is intentionally horizontally scrollable because shrinking 6–10 generations into a phone viewport would make the ancestry unreadable.

## Visual acceptance source

Continue to compare every substantial UI change with:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`
