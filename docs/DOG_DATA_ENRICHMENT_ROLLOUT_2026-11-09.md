# CaneCorsoAncestry dog data enrichment — operational review

This introduces a **read-only prioritized staff worklist**, not a mass-verification job, scraped-image importer, registration system, or new breed record source.

## Staff workflow

1. Open **Moderation → Data Health → Open prioritized review queue**. The shortlist includes up to 1,000 most-searched published dogs and 250 newest published dogs, **plus** published dogs with active disputes or structurally impossible parent/date relationships. Score represents urgency, not certainty, and the displayed count refers to this cohort only.
2. Each row distinguishes independent evidence signals: documented source URL/file; timestamp-reviewed URL/file; reviewed *pedigree/registry* file; prior staff approval audit; real/trusted photo availability; potential identical managed photo on another published dog; and unresolved dispute.
3. Use **Reconcile prior approvals** to find published dogs whose prior moderation approval exists but whose DogSource record has no timestamp-reviewed actual URL/file. The previous approval remains valid **as an approval event**, not proof that a source established identity or parentage. Inspect the recorded actor, linked source evidence, and exact dog before any fresh review.
4. Use **Possible reused photos** to find SHA-256-identical managed uploads on at least two different published dogs. A single dog having multiple copies of a photo does not trigger the alert. An image match is neither evidence of a duplicate canonical dog nor permission to reuse, delete, or move a photograph. Respect original licensing/consent.
5. Keep using the existing archive-wide **Review parentage evidence**, **Photo gaps**, **Missing sources**, and **Unknown sex** filters. The existing owner-only registration-backed duplicate investigation is deliberately separate and may identify candidates without merging them.
6. When an original document genuinely supports a claim, use the existing authorized source or moderation workflow and preserve reviewer/date/audit details. Do not backfill DogSource verification timestamps based on old approval flags or source titles alone. A reviewed health document is *not* parentage evidence.
7. Review the highest-priority actual 500–1,000 cases in batches, preserving canonical identity and all repeat-ancestor positions. Dog owners/breeders must supply legitimate photographs and permissions; a historical dog with no genuine photo should remain without one.

## Privacy and safety

- The priority review is permission-gated by the existing staff role and restricts its candidate set to `published_dogs()`. Private, kennel-hidden and moderation-hidden dogs are not shown, and their private images are not counted toward public photo reuse alerts.
- No new records, automatically approved dogs, verification markers, parent assignments, image transfers or database schema migrations are created by the review queue.
- A real timestamp-reviewed source URL/document is a better evidence signal, but still does not prove its contents; reviewers must check which claim it actually supports.
- Source coverage and actual independent review coverage must remain separate indicators in production reporting.

## Verification / rollout

Focused tests cover visibility boundaries, historical approvals, health-vs-parentage provenance, duplicate upload hashes across different dogs, staff permission checks and review priority order. Production checkout should inspect the rendered queue, report its cohort counts, and confirm no authoritative Oracle data changed. A score should rise only after documented reviewed sources and legitimate images actually improve, never solely because the queue was shipped.
