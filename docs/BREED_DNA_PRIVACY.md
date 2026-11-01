# Breed DNA composition and consent

Cane Corso Ancestry only records DNA **breed estimates supplied by third-party testing laboratories**. A moderator reviews the actual uploaded evidence. The platform does not perform genetic testing, certify biological purity or act as a breed registry.

The kennel owner may submit a lab report through the existing dog Health & DNA form (`?type=breed`). The testing company, Cane Corso percentage and other breed percentages must sum to 100%, and the owner must explicitly consent to public display of the reviewed summary. Test evidence remains private during moderation.

The owner separately chooses whether to publish the **entire uploaded report**, including any identifiers, upon moderator approval. This is unchecked by default. Without that separate consent, only the company's name and breed percentages appear on the public dog profile. Existing approved medical tests and parentage submissions are unaffected.

Document visibility changes may never disclose a DNA report if the original owner did not give full-report consent; there is no implicit consent through a moderator or editor. Corrections should be submitted as fresh evidence. The profile selects the most recently tested approved report.

Deployment requires additive migration `registry.0018_breed_dna_report` against the canonical Oracle PostgreSQL database and the existing static-asset pipeline. No external genetic-company API access is claimed.

## Super Admin historical laboratory evidence (October 2026)

The Super Admin workspace `/member/moderation/health-dna/` can record evidence-reviewed
health screens, genetic markers and historical breed composition for an existing
canonical dog. A genuine report upload (max 20 MB), source/reference and explicit
review attestation are required; the operation creates an audit entry and
verification event. Uploaded staff evidence is always staff-only, even if a
kennel member knows the media path.

Historical breed-composition records are recorded with `consent_public_summary=False`
and `consent_full_report=False`. They are not visible on public dog profiles or
in direct-relative health summaries until the kennel owner provides consent via
the existing member submission and moderation workflow. Staff cannot manufacture
owner consent. Existing approved member reports retain their original summary
consent through the additive migration default. The Super Admin can withdraw
all public DNA details for a particular dog; evidence and audit history remain.

## Reviewed inherited conditions and repeat uploads

DSRA, NCL1 and CMR1 appear as Clear, Carrier, Affected, or Not tested on
published dog profiles. Only specifically approved laboratory-evidenced
results can produce a health classification. No available result (including
ambiguous results) means Not tested, NEVER a presumption of genetic clearance.
DNA breed-composition percentages can be published by an authorized moderator after the underlying report has been verified; the owner's original consent record is not changed.
The original member Health & DNA submission form is reusable for newly
received test certificates, including after dog/pedigree publication.

## Moderator report transcription and public-summary switches

Moderation displays the privately uploaded image or PDF while entering the
laboratory's DSRA, NCL1 and CMR1 results as structured data. Results can be
enabled individually; absent results are never automatically interpreted as
Clear. They remain pending until a separate moderator approval. Approved typed
records are independently show/hide toggleable with audit history and stored
private evidence retained. Verified breed percentages can be published by any active authorized moderator.
The public dog profile displays "No available records" when nothing verified
is being published. Raw genetic/medical certificates stay private.

**Policy update:** Full laboratory reports and images are kept private regardless of any older full-report consent flag. Only evidence-reviewed and publication-approved typed breed percentages and independently reviewed health results can be published. The full-file publication option has been retired.

## Authorized moderator publication control (November 2026)

Every active Moderator, Senior Moderator and Super Admin can publish a previously
verified, structured breed-DNA summary through **Manage dogs → Health values →
Approved health records → Public**, or **Edit health record → Save & make Public**.
Publication is an explicit staff decision, not a request for owner authorization.
Staff may record an administrative decision or existing verbal/written confirmation.
The decision is separately audited and the original owner consent field is **never
changed** by a staff action. Suspended or deregistered staff and members cannot
use these publication controls.

The **Private** action hides the public summary immediately; any authorized
moderator can restore it. The Super Admin-only **Withdraw all DNA publication**
removes all existing staff publication decisions and owner-publication grants
from the displayed summaries. Raw certificates and uploaded laboratory files
remain private under the media access policy regardless of either summary
setting. Unstructured or unverified breed-purity prose is never made public.
