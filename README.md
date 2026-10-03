# Cane Corso Ancestry

A modern Cane Corso pedigree and ancestry platform.

## Product direction

This repository is intentionally separate from Bellissimo Geni, while verified Bellissimo pedigree data may be imported as one source dataset.

The owner requirement is explicit: **this is a pedigree website, not a registry**.

### Owner-approved visual direction

The supplied design references are authoritative:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Keep the black/charcoal, warm ivory and restrained gold visual language unless the owner explicitly changes the brief.

## Active production stack

The live system currently uses:

- **Cloudflare Workers site edge** — public website endpoint, public-page cache and origin warm-up
- **Northflank** — Django/Gunicorn application origin and static files
- **Supabase PostgreSQL** — canonical relational database through the session pooler
- **Cloudflare R2** — uploaded dog photos, evidence and documents through the media Worker

Public website:

`https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`

Northflank origin:

`https://web--canecorsoancestry--4w9gl8jxj4yr.code.run`

R2 media gateway:

`https://canecorsoancestry-edge.aighewieghosa111.workers.dev`

No custom domain is configured or assumed.

## Technology

- Python 3.13 / Django 5.2
- PostgreSQL
- Django templates
- Gunicorn
- WhiteNoise for static files
- Cloudflare Workers and R2
- GitHub Actions with focused, change-scoped checks

External registration numbers may be stored and displayed with their issuing body, but Cane Corso Ancestry does not present itself as the issuing registry.

## Paid submissions

New pedigree records use Paystack-backed submission packages:

- **₦500** — one dog;
- **₦1,000** — 2–6 dogs;
- **₦1,000** — one litter plus the puppies belonging to that litter.

Payment never publishes a record. The kennel/owner must already be approved, and every submitted dog or litter remains in the admin moderation queue until an administrator verifies and approves it.

## Documentation

- `PROJECT_PLAN.md` — product plan
- `docs/OWNER_REQUIREMENTS.md` — terminology and owner requirements
- `ARCHITECTURE.md` — active technical architecture
- `docs/PRODUCTION_DEPLOYMENT.md` — current deployment/runbook
- `SKILL.md` — repository working rules
- `docs/design-reference/` — owner-approved visual references
