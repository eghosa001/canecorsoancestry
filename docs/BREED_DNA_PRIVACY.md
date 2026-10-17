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
