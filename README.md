# Cane Corso Ancestry

A modern Cane Corso pedigree and ancestry platform.

## Product direction

This repository is intentionally separate from Bellissimo Geni, while verified Bellissimo pedigree data may be imported as one source dataset.

### Owner-approved visual direction

The supplied WhatsApp design mockups are the authoritative visual reference for the project. They must be preserved in `docs/design-reference/` and used as the baseline when implementing public pages and the owner/member dashboard.

Do not redesign away from the supplied black/charcoal, warm ivory and restrained gold visual language unless the owner explicitly requests it.

### Technology

- Python
- Django
- PostgreSQL
- Django templates + progressive enhancement/HTMX where appropriate
- Django REST Framework only where an API materially helps
- Production media/storage separated from source code

The platform is an ancestry/pedigree database, not an official registry. External registration numbers may be stored and shown with their issuing body.

See `PROJECT_PLAN.md` for the implementation plan.
