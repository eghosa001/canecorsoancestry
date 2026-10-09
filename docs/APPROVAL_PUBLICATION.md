# Approval-to-publication contract

A member submission is **not** public simply because it has been submitted.
Only a final authorized moderator/super-admin review creates or changes the
canonical record. High-risk cases may require a second independent reviewer.

| Final approved submission | Visible to visitors? | Expected page |
| --- | --- | --- |
| New dog | Yes, dog profile/search; new photo becomes primary if supplied | `/dogs/<slug>/`, `/dogs/?q=...` |
| Additional dog photo | Yes after approval, never before | Primary hero, or gallery for a non-primary photo |
| Dog correction | Yes for already-public dogs | Existing stable-slug profile, pedigree, search |
| Health/DNA result | The verified result yes (for a public dog) | Dog profile Health & DNA; supporting evidence stays private |
| Dog document | Only if separately flagged public | Dog profile Published documents; private evidence stays private |
| Document visibility | Yes if request sets public; otherwise hides | Dog profile Published documents |
| New kennel / kennel update | Visible kennel metadata | `/kennels/`, `/kennels/<slug>/` |
| Kennel ownership claim | Ownership permissions apply after approval; not necessarily shown publicly | Member/admin membership |
| New litter / litter correction | Yes for public litter | Litter detail and kennel listing |

An approved correction to a **private** dog does not make the dog public.
Microchip IDs and private supporting documents are retained securely, not
displayed in the public profile. Homepage featured cards and directory pages
are **ranked and paginated**, so publication does not guarantee first-page
placement. An image-less approved dog is searchable by name but excluded
from the photo-only default browse page until a photograph is approved.

## Integrity checks

- `registry/tests_approved_publication.py` exercises pending and approved
  states through actual Django public routes and media authorization.
- `scripts/oracle_runner/audit_approved_publication.py` runs read-only inside
  the production Oracle Django container and compares approved member
  submission references with current canonical dog/image/health/document/
  kennel/litter records. Samples current approved photos with R2 HEAD and
  public Cloudflare HTTP image delivery checks.
- `.github/workflows/approved-publication-audit.yml` executes only from
  protected `main` (manual dispatch or weekly schedule), never untrusted PRs.
- The approval transaction checks uploaded files still exist in media storage
  **before** marking a photo, new dog with a photo, health record or document
  approved. Missing files keep the submission pending for review.
- Cloudflare does not cache dynamic HTML or query results. Django clears
  homepage and directory metadata after a successful approval transaction.

Historical approvals might later be superseded, deleted by an administrator,
or explicitly made private; aggregate discrepancy counts require review in
that context and are not themselves evidence of unauthorized publication.
