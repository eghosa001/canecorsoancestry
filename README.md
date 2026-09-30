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

- Python 3.13 / Django 5.2
- PostgreSQL
- Django templates + progressive enhancement/HTMX where appropriate
- Cloudflare Worker + R2 for edge routing, static assets and private media
- Render for the Django web service
- Aiven for the production PostgreSQL database
- GitHub Actions for CI, migration and deployment checks

External registration numbers may be stored and displayed with their issuing body, but Cane Corso Ancestry does not present itself as the issuing registry.

## Production stack

The target production path is:

`Cloudflare Worker → Render Django → Aiven PostgreSQL`

Cloudflare R2 stores user-uploaded media and evidence. The Render origin can be protected with an HMAC edge gate so normal application traffic enters through Cloudflare. Supabase remains only as the temporary source database until the verified one-time Aiven migration is complete.

See `docs/PRODUCTION_DEPLOYMENT.md` for the exact setup and cutover procedure.

## Documentation

- `PROJECT_PLAN.md` — phased product plan
- `docs/OWNER_REQUIREMENTS.md` — owner requirements and terminology guardrails
- `ARCHITECTURE.md` — technical architecture
- `docs/PRODUCTION_DEPLOYMENT.md` — Render/Aiven/Cloudflare setup and migration runbook
- `SKILL.md` — working rules for future changes
- `docs/design-reference/` — permanent owner-approved visual references
