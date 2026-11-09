# CaneCorsoAncestry: evidence needed to raise the weakest production scores

This is an **operational checklist**, not a claim that the live service passed. Existing public data and verification states must not be fabricated to improve a score. The site is a pedigree research website, not a registry.

## Data quality — highest priority

- Staff: open **Data Health → Review parentage evidence**. Start with most-searched public dogs. A dog with two parent links is not automatically proven to have correct parentage. Check the dog's original pedigree or registry document, issuing authority, identity/registration information, exact sire and dam, and conflicting sources. Log the result and source URL/upload using existing staff moderation permissions.
- Staff: use the existing **Photo gaps in existing dogs** queue. Ask the kennel/breeder for an identifiable original dog photograph and permission to publish it; never use AI-generated or placeholder photos as evidence.
- Staff: work through **Missing sources**, **Unreviewed sources**, discrepancies, duplicates, and pending disputes without changing status until the evidence is reviewed. Name matches alone never authorize a merge.
- Owner: supply breeder or owner documents where source records cannot be independently obtained. Never upload private certificates directly into public pages; use the protected evidence workflow.
- Run a read-only `python manage.py report_data_quality` and approved full data-integrity audit on the actual Oracle PostgreSQL environment when operational access is available; preserve a dated anonymized snapshot of coverage and critical violations. Do **not** modify the live database merely to increase the statistics.
- Success evidence: dated, sampled human review logs; source coverage specific to parentage, photo provenance, zero unresolved impossible parent relationships or cycles. A source review timestamp alone does **not** certify correctness.

## Performance and mobile usability

- The pedigree viewer now indexes canonical dog IDs once, avoiding a complete node scan on every hover/focus. Mobile generation navigation remains single-generation and includes all recorded ancestors, with summarized unknown positions.
- Owner/tester: load a real 4-, 6-, 8- and 10-generation tree on an Android phone and iPhone Safari; try a known shared ancestor, swipes, the generation picker, keyboard/VoiceOver/TalkBack, PDF printing, and CSV export. Record device, browser, tree size, download correctness, and screenshots of failures.
- Operator: run the existing **focused** browser and Oracle performance diagnostics against a production-like database, not a broad unconditional test suite. Capture p50/p95 server response and client interaction time, database query counts, memory, and 3G/4G LCP/INP/CLS on sample large trees; compare after deployment.
- Success evidence: no inaccessible generations or private records leaked, smooth interaction on target phones, and real-world measurements meeting the owner's accepted performance budget. No numeric score increase until those measurements exist.

## Accessibility and search visibility

- Owner: configure/verify the actual Search Console property once a canonical domain is selected. Check sitemap/robots/indexing and record real URL inspection results. Do not submit member-gated pedigree URLs as public search content.
- Tester: run page-focused WCAG 2.2 AA checks on the home/search, public dog detail, member pedigree, staff worklists, login/recovery and purchase flow; include keyboard, screen-reader, text zoom, contrast, touch targets, and reduced-motion checks. Log issues and close with retests.
- Success evidence: reproducible audit results and verified live indexing data, not a self-assigned site score.

## Owner-only live release gates

1. **Account recovery**: verify real SMTP sending and inbox receipt for password-reset and verification emails on an authorized test account, including expired-token behavior. No passwords or mail credentials in GitHub or chat.
2. **Membership**: complete signup, email verification, kennel membership/permissions, paid submission entitlement and approved-vs-private viewing with genuine test accounts. Confirm no moderation bypass.
3. **Paystack**: with controlled low-value real transactions, confirm checkout, webhook signature, idempotency, paid entitlement, reconciliation and refunds/failed paths. Never share secret keys.
4. **Alerting**: trigger a safe, authorized test alert and confirm the actual recipient receives it; check uptime/backup failure alarms and incident owner.
5. **Backups**: perform an isolated test restore of a fresh encrypted PostgreSQL backup, checksum/row-count verification and timed recovery. **Never** restore into the live authoritative Oracle database.
6. **Release**: verify current deployed build SHA matches the approved main branch via existing release attestation and focused smoke tests; do not assume a merged PR is deployed.

Record a date, reviewer, environment, result and link to evidence for every completed gate. Until this is done, production scores remain provisional.