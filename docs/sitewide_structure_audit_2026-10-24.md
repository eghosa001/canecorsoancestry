# Site-wide structure and navigation audit — 24 October 2026

## Inventory and methodology

The Django repository contains 66 HTML templates across public, member, moderator,
Super Admin, authentication, legal, error and shared component families.
Of these, 61 are standalone-page templates or admin pages after excluding
partial templates and transactional email markup.

The audit inspected template composition, navigation landmarks, page headings,
action counts, form density, progressive disclosure, overflow containment and
the distinction between everyday versus privileged operations. This is a
source/template audit complemented by WebKit browser regression tests; it is not
a claim that all 61 pages were manually screenshot-compared in every viewport.

## Prioritized findings

| Area | Evidence | Structural treatment |
| --- | --- | --- |
| Member dashboard | 52 links, 14 panel surfaces and a long local navigation | Keep desktop sidebar and collapsed mobile member menu; make task cards 2 columns on desktop and 1 on phone, with consistent sections |
| Staff review queue | 10 forms and 20 button-style actions across review and duplicate tools | Prioritize Manage dogs, place secondary header actions in an accessible More tools disclosure; preserve existing on-demand duplicate disclosure |
| Verification dashboard | 22 panels and 9 already-disclosed groups; high-risk staff deactivation presented ahead of work queue | Lead with pending/at-risk metrics and proposals; move staff access control into the advanced administration area and keep required confirmations |
| Staff/member navigation | Flat staff tool strip; current-state mapping misses several detail pages | Group primary and secondary destinations; responsive native details menu and correct active-route states; preserve Super Admin-only links |
| Dog profile and home cards | Previously verified clipped tabs, long health values and popular-card overflow at 375–430px | Retain the already released single-column mobile cards, readable tabs and stacked health results |
| Pedigree and pairing analysis | Dense tree controls, six jump sections, sensitive COI information | Keep horizontal tree exploration bounded to its own region; allow pairing sections to wrap into readable navigation rather than forcing one row; do not change COI |
| Search / kennel / litter / statistics | Broad filters, dense cards and occasional wide tables | Shared page width, wrapping headings, form grids, card containment and scroll-limited tabular data |
| Authentication, payments and policies | Forms and prose spread across different legacy CSS conventions | Reuse reading measure and responsive inputs, keeping payment and privacy language intact |
| Django Admin | Separate authentication and protected admin chrome | Existing theme and permissions stay unchanged; Django Admin receives no blanket public-page navigation replacement |

## Navigation rules

1. Primary task destinations remain visible in desktop workspaces.
2. Secondary admin tools appear under an explicit, keyboard-accessible disclosure.
3. On mobile, the workspace is one compact Browse sections control; opening it reveals navigable 46px+ items.
4. Role boundaries are decided on the server, never by UI visibility alone.
5. The member dashboard retains its own dedicated sidebar and does not duplicate the global workspace strip.
6. Current-page indicators follow the actual route, including dog creation, DNA records, merging, documents, pairings, and disputes.
7. Advanced actions may be disclosed progressively, but cannot become unreachable or lose audit/confirmation requirements.

## Verification scope

- Django role and navigation assertions across member, reviewer and Super Admin identities.
- Existing WebKit iPhone interaction smoke.
- Additional WebKit width checks at 375, 430, 834 and 1280 CSS pixels on public/member page families.
- Full SQLite and PostgreSQL release audit, fast policy and production settings checks.
- Protected Oracle production exact-SHA verification after merge.

## Explicit limits

No backend data, formula, payment, permission or migration change is intended.
Automated width and interaction checks catch clipping and broken flows but do not
by themselves demonstrate a perfect design or guarantee a 9+/10 subjective score.
A complete visual acceptance pass would require screenshots for every role/page,
including private data states, alongside the source and automated checks.
