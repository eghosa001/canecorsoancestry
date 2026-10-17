# Breed DNA composition and consent

Cane Corso Ancestry only records DNA **breed estimates supplied by third-party testing laboratories**. A moderator reviews the actual uploaded evidence. The platform does not perform genetic testing, certify biological purity or act as a breed registry.

The kennel owner may submit a lab report through the existing dog Health & DNA form (`?type=breed`). The testing company, Cane Corso percentage and other breed percentages must sum to 100%, and the owner must explicitly consent to public display of the reviewed summary. Test evidence remains private during moderation.

The owner separately chooses whether to publish the **entire uploaded report**, including any identifiers, upon moderator approval. This is unchecked by default. Without that separate consent, only the company's name and breed percentages appear on the public dog profile. Existing approved medical tests and parentage submissions are unaffected.

Document visibility changes may never disclose a DNA report if the original owner did not give full-report consent; there is no implicit consent through a moderator or editor. Corrections should be submitted as fresh evidence. The profile selects the most recently tested approved report.

Deployment requires additive migration `registry.0018_breed_dna_report` against the canonical Oracle PostgreSQL database and the existing static-asset pipeline. No external genetic-company API access is claimed.
