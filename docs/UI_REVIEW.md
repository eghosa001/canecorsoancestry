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


## Advanced pedigree analysis visual review

The pedigree smoke coverage now asserts the advanced analysis surface in addition to capturing screenshots.

Confirmed by the automated desktop/mobile run:

- public pedigree analysis renders the Ancestor contribution and Linebreeding paths sections;
- public and member mobile pedigree pages render the compact analysis summary;
- the contribution, coverage, unique-ancestor and repeated-ancestor cards collapse responsively instead of forcing global horizontal overflow;
- detailed contribution and linebreeding panels collapse to one column on narrow screens;
- deep 6–10 generation pedigree boards remain intentionally horizontally scrollable rather than shrinking names into unreadable columns;
- public export and member-scoped export controls are separate;
- print controls are excluded from the print layout, which switches the report to a readable landscape document treatment;
- the advanced analysis is visually separated from the editable/moderated canonical record and does not imply that analysis changes pedigree data.

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

The mobile smoke test confirms ordinary public/member pages do not create unintended global horizontal overflow. It also captures both the public and member pedigree analysis summaries at 390 × 844.

The pedigree board remains intentionally horizontally scrollable because compressing 6–10 generations into a phone viewport would make the ancestry unreadable. The analysis summary and detailed analysis panels themselves reflow to the phone width.

## Visual acceptance source

Continue to compare every substantial UI change with:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`
