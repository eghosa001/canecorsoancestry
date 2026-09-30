# Cane Corso Ancestry

A modern Cane Corso pedigree and ancestry platform.

## Product direction

This repository is intentionally separate from Bellissimo Geni, while verified Bellissimo pedigree data may be imported as one source dataset.

The owner requirement is explicit: **this is a pedigree website, not a registry**.

### Owner-approved visual direction

The supplied WhatsApp design mockups are the authoritative visual reference:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Keep the black/charcoal, warm ivory and restrained gold visual language unless the owner explicitly changes the brief.

## Production stack

The production architecture is deliberately limited to three services:

- **Render** — Django application and static files
- **Aiven PostgreSQL** — canonical relational database
- **Cloudflare R2** — uploaded dog photos, evidence and documents

The application is currently available directly at:

`https://canecorsoancestry.onrender.com`

Cloudflare is **not** an application proxy. A tiny Workers endpoint exists only because it provides authenticated access between Django and the private R2 bucket.

There is no active Supabase, Railway, Google Cloud Run, GitHub Pages preview or custom-domain edge dependency in the application runtime.

## Technology

- Python 3.13 / Django 5.2
- PostgreSQL
- Django templates
- Gunicorn
- WhiteNoise for static files
- Cloudflare R2 for durable media
- Playwright for browser regression checks
- GitHub Actions for focused CI and R2 deployment

External registration numbers may be stored and displayed with their issuing body, but Cane Corso Ancestry does not present itself as the issuing registry.

## Documentation

- `PROJECT_PLAN.md` — product plan
- `docs/OWNER_REQUIREMENTS.md` — terminology and owner requirements
- `ARCHITECTURE.md` — active technical architecture
- `docs/PRODUCTION_DEPLOYMENT.md` — current deployment/runbook
- `SKILL.md` — repository working rules
- `docs/design-reference/` — owner-approved visual references
