# Verification & Governance Upgrade — Implementation Ledger

This document tracks the October 2026 verification/governance upgrade requested for Cane Corso Ancestry.

**Design principle:** *Admins review the evidence; admins do not erase the evidence.*

**Compatibility rule:** this upgrade is additive. Existing dogs, pedigrees, kennel profiles, members, submissions, Paystack records, authentication and public URLs are preserved. Canonical `Dog` and `Litter` UUIDs remain the record identities.

**Current package pricing preserved from `main`:** ₦500 single dog; ₦1,500 for 2–4 dogs from one verified kennel; ₦200 for one litter and its puppies. The older pricing figures repeated in the specification were intentionally not used to undo the newer approved pricing change.

## Architecture before this upgrade

- Django server-rendered application.
- PostgreSQL in production.
- Canonical `Dog` model with sire, dam, kennel and optional litter relationships.
- Canonical `Litter` model with sire, dam, kennel and DOB.
- `Submission` moderation workflow.
- Paystack `SubmissionPayment` + `PaymentSubmissionLink` server-side entitlement.
- Existing kennel memberships, verification events, disputes, duplicate intelligence and moderation audit.
- Private R2 media gateway in hosted production.

## Completion checklist

- [x] **1. Litter integrity checking**
  - `Litter` now retains country and declared puppy count in addition to existing ID/code, sire, dam, DOB and kennel.
  - Every litter puppy remains an individual dog submission and later an individual canonical `Dog`.
  - Server checks compare litter ID, kennel, sire, dam, DOB, declared count, payment linkage and other submitted littermates.
  - Registration, microchip, duplicate identity, duplicate pending submission and duplicate image evidence checks are included where the underlying information exists.
  - Exact expected/submitted values are stored on verification findings.
  - Conflicts create review findings; they do not automatically reject the submission.

- [x] **2. Flags are not treated as fraud**
  - GREEN / YELLOW / RED describe consistency/risk, not intent.
  - Flagged submissions remain pending for human review.
  - Review UI explicitly states that a warning is not an accusation.
  - Missing information is labelled as incomplete/unknown rather than fabricated.

- [x] **3. Individual dog records**
  - `Dog` remains the canonical individual record with a unique UUID.
  - `Dog.litter` links the individual dog to the litter.
  - A litter never becomes a combined “giant dog” row.
  - Review UI shows the canonical Dog UUID for approved littermates.

- [x] **4. Administrative authority levels**
  - Owner / Super Admin.
  - Senior Reviewer.
  - Reviewer.
  - Explicit “No verification role” assignment prevents verification access without revoking unrelated Django staff access.
  - Existing staff are backward-compatible as Reviewers until the Owner explicitly changes their verification role.

- [x] **5. Two-person approval for high-risk overrides**
  - Rules have configurable risk and `second_approval_required`.
  - High-risk override creates an append-only first-review decision.
  - The same administrator cannot perform second approval.
  - Second review is limited to Senior Reviewer / Owner authority.
  - Publication only happens after the independent second approval succeeds.

- [x] **6. Immutable audit trail**
  - Important decisions create `ModerationAudit` and/or append-only `SubmissionReview` rows.
  - Application-level save/delete protection prevents edits/deletes of existing audit/review rows.
  - Django Admin exposes these records as view-only.
  - Audit rows snapshot actor, submission, dog, kennel and litter identifiers so IDs remain historically visible even if an FK later becomes null.
  - Protected record corrections capture old → new values.
  - Warning snapshots, evidence snapshots, reasons and first/second reviewer IDs are retained.

- [x] **7. Admin override**
  - A flagged case cannot use normal Approve.
  - Override reason is mandatory.
  - YELLOW override is recorded.
  - Rules configured for second approval transition to `AWAITING_SECOND`.
  - RED defaults are configured for second approval.

- [x] **8. Automated verification engine**
  - Litter: DOB, sire, dam, litter ID, kennel, declared puppy count, duplicate litter, cross-littermate DOB consistency.
  - Dog: duplicate canonical identity, duplicate pending submission, registration, microchip, image hash, DOB/sex/parent conflicts where comparable.
  - Pedigree: same-parent conflict, parent-role sex conflict, parent born on/after offspring, unusually young parent, protected ancestry changes.
  - Payment: confirmed server-side entitlement, package type, member, kennel, slot kind and same paid litter package.
  - Checks are progressive: missing historical identifiers remain unknown rather than being invented.

- [x] **9. Explainable risk levels**
  - GREEN — pass / no blocking inconsistency detected.
  - YELLOW — human review.
  - RED — high risk.
  - Every finding has a rule code, message, expected value, submitted value and metadata.
  - Admin detail shows PASS / CONFLICT / REVIEW rows and the specific warnings that produced the risk.
  - GREEN informational rules do not block normal approval.

- [x] **10. Admin activity monitoring**
  - Owner dashboard reports reviews, approvals, rejections, flagged cases, overrides, override percentage, high-risk approvals and average review time.
  - Override-rate signal is compared with established peer reviewers.
  - It is labelled “review recommended”; it does not accuse the administrator of misconduct.

- [x] **11. No trust in client-side data**
  - Verification, payment entitlement, litter membership, publication, permissions, override authority and second approval are enforced in Django services/views.
  - Paystack status remains read-only in Django Admin.
  - Submission rows are view-only in Django Admin.
  - Browser payloads cannot directly set approval/publication state.

- [x] **12. Payment package eligibility**
  - The currently approved production prices remain unchanged.
  - Dog submissions are bound to the paid verified kennel.
  - Litter puppies must use the same paid litter package and kennel as the referenced litter.
  - A forged litter reference or wrong package creates a RED entitlement finding and cannot publish.
  - Puppy count can exceed the declaration only by entering a flagged review path.
  - Adult dogs are not rejected merely because they are adults; genuine adult littermates can be linked to the same litter when litter facts/evidence support it.

- [x] **13. Private evidence**
  - Private evidence types: pedigree, registration, breeding record, litter record, kennel document, DNA/parentage, identity photo and other.
  - Evidence request and fulfilment are linked to the submission.
  - Uploaded files are SHA-256 fingerprinted.
  - Verification evidence is separate from public `DogDocument`.
  - Anonymous media access is denied; production R2 delivery remains signed through the existing gateway.
  - Evidence upload triggers re-verification.

- [x] **14. Relational database design**
  - Existing `Kennel → Litter → Dog → Parents` structure is retained.
  - New verification records reference `Submission` rather than duplicating canonical dogs.
  - Microchip/identity number is a related canonical dog identity record.
  - Litter grouping uses `Dog.litter`; individual dog identity is unchanged.

- [x] **15. Existing-data preservation / migration strategy**
  - One additive migration extends existing tables and creates verification/governance tables.
  - No destructive data rewrite.
  - Existing moderation audit rows receive identifier snapshots.
  - Existing dogs/litters receive safe defaults for new lock fields.
  - Verification rules are seeded idempotently.
  - Existing public records remain intact.

- [x] **16. Admin review screen**
  - Submission/member/kennel/payment/type/status/risk.
  - PASS/CONFLICT/REVIEW automated checklist.
  - Exact warning expected/submitted values.
  - Proposed historical changes.
  - Full litter-group view with each submitted dog.
  - Private evidence list/download.
  - Request evidence / Approve / Reject / Approve with override.
  - Dedicated second-review state and controls.
  - Append-only human review and system audit timeline.

- [x] **17. Record locking**
  - Dog and litter support explicit Owner/Super Admin lock state.
  - Lock/unlock requires a reason and audit event.
  - Published DOB, sire, dam, litter, sex, registration and microchip changes are protected even without an explicit lock.
  - An explicit lock elevates corrections into high-risk review.
  - Django Admin cannot silently flip public/lock state or protected published ancestry fields.

- [x] **18. Owner master control**
  - Pending count.
  - Flagged queue.
  - High-risk queue.
  - Second-approval queue.
  - Override history.
  - Reviewer activity.
  - Audit history link.
  - Recently changed protected records.
  - Locked dog/litter records.
  - Admin role management.
  - Verification rule management.

- [x] **19. Incremental implementation and testing**
  - Existing architecture/schema/payment/moderation paths were inspected before modification.
  - Changes were implemented on isolated branch `verification-governance-system`.
  - Focused regression tests live in `accounts/tests_verification.py`.
  - Test scope is limited to the changed verification/payment/moderation behavior in accordance with repository policy.
  - No broad unrelated test suite, lint sweep or unrelated CI job is required by this change.

## New/extended models

- `ModerationRoleAssignment`
- `VerificationRule`
- `VerificationFinding`
- `EvidenceRequest`
- `SubmissionEvidence`
- `SubmissionReview`
- `DogIdentityNumber`
- Extended `Submission` risk/verification state.
- Extended `Litter` country/declared count/record lock state.
- Extended `Dog` record lock state.
- Extended `DogImage` SHA-256 fingerprint.
- Extended `ModerationAudit` immutable subject-ID snapshots.

## Security notes

- Verification documents are private by default.
- R2 is accessed through the existing signed gateway in hosted production.
- Important publication decisions are rechecked in the service immediately before canonical mutation.
- High-risk approval requires two different authorized accounts.
- Django Admin cannot directly mutate payment state or submission publication state.
- Verification role removal does not disable unrelated Django staff permissions.
- Automated consistency checks are decision support. They do not infer fraud or invent missing pedigree facts.

## Focused regression cases

- Litter DOB mismatch remains pending and includes expected/submitted values.
- Flagged case cannot use normal approval.
- First high-risk reviewer cannot second-approve their own override.
- Independent second reviewer can publish after the required override path.
- Approved litter puppy becomes an independent UUID `Dog` linked to the canonical litter.
- Normal reviewer cannot override RED findings.
- Protected published ancestry correction becomes high risk.
- Audit rows reject edit/delete attempts.
- Wrong payment package cannot masquerade as a litter entitlement.
- Private verification evidence is not anonymously readable.

