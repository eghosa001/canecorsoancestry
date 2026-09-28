# Cane Corso Ancestry

A modern Cane Corso pedigree and ancestry platform.

## Product direction

This repository is intentionally separate from Bellissimo Geni, while verified Bellissimo pedigree data may be imported as one source dataset.

The owner requirement is explicit: **this is a pedigree website, not a registry**.

### Owner-approved visual direction

The supplied WhatsApp design mockups are the authoritative visual reference for the project. They are preserved at:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

They define the visual baseline for public pages and the owner/member dashboard. Do not redesign away from the supplied black/charcoal, warm ivory and restrained gold language unless the owner explicitly requests it.

### Technology

- Python
- Django
- PostgreSQL
- Django templates + progressive enhancement/HTMX where appropriate
- Django REST Framework only where an API materially helps
- production media/storage separated from source code

External registration numbers may be stored and displayed with their issuing body, but Cane Corso Ancestry does not present itself as the issuing registry.

## Documentation

- `PROJECT_PLAN.md` — phased product plan
- `docs/OWNER_REQUIREMENTS.md` — owner requirements and terminology guardrails
- `ARCHITECTURE.md` — technical architecture
- `SKILL.md` — working rules for future changes
- `docs/design-reference/` — permanent owner-approved visual references
