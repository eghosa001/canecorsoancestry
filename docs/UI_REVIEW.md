# UI Review

Last reviewed: 28 September 2026

## Automated browser coverage

The Playwright smoke workflow renders the live Django application after migrations and a Bellissimo seed import.

Acceptance viewports:

- desktop: 1440 × 1000
- mobile: 390 × 844

The workflow checks global horizontal overflow on ordinary pages and captures:

- homepage;
- dog search/profile;
- public pedigree;
- member dashboard;
- My Pedigrees;
- private member pedigree detail;
- My Litters;
- My Documents;
- My Review Cases;
- moderation/review queue;
- moderation audit history;
- submit-dog form;
- claimable kennel profile;
- kennel ownership claim form.

## Moderation intelligence visual review

The moderation screenshot seed intentionally includes:

- one high-priority pending correction;
- a real before/after field diff;
- one open pedigree dispute;
- one audit event.

The final moderation page was manually reviewed after the browser run.

Confirmed:

- queue filters fit the desktop layout;
- priority and assignment states remain readable;
- proposed changes are visually separated into canonical vs submitted values;
- duplicate intelligence is separate from the irreversible merge controls;
- dispute actions are clearly isolated;
- bulk actions sit above the selected review cards and do not overlap merge/verification panels;
- bulk approval is visibly unavailable;
- the audit page uses the same dark/gold data-oriented language;
- My Review Cases remains readable on the 390px mobile viewport.

## Comparison with the owner references

The implementation continues the supplied reference language:

- near-black/charcoal surfaces;
- restrained gold;
- warm ivory typography;
- strong serif headings;
- compact data-rich cards;
- explicit pedigree relationships;
- left-rail member dashboard on desktop;
- separated member and moderator workspaces.

## Current media limitation

The imported Bellissimo ancestry seed contains pedigree/identity data but does not provide approved production dog image files to this Django media store.

Current CCA placeholders are intentional.

Do **not** fabricate a specific dog's photograph or reuse an unrelated dog image merely to fill a card. Approved photos can enter through the member photo workflow, be reviewed, and then attach to the canonical dog.

## Mobile

The mobile smoke test confirms ordinary public/member pages do not create unintended global horizontal overflow.

The pedigree board remains intentionally horizontally scrollable because compressing 6–10 generations into a phone viewport would make the ancestry unreadable.

## Visual acceptance source

Continue to compare every substantial UI change with:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`
