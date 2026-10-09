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

## Active production stack (verified 9 October 2026)

The machine-readable source of truth is [`infra/active-services.json`](infra/active-services.json). Run `python3 scripts/verify_active_services.py` to check that deployment configuration still matches this inventory.

- **Cloudflare Workers site edge** — public endpoint, caching, and a **private VPC binding** to Oracle; see `src/site-edge.js`, `wrangler.site.toml`.
- **Oracle Cloud VM** — sole live Django/Gunicorn application origin, running in Podman on loopback port 18080; see `scripts/oracle_runner/stage_django.sh`.
- **Oracle-local PostgreSQL 17** — the authoritative `cca_live` database, reachable only through a private Podman network; no remote Supabase round trips in production.
- **Cloudflare R2 + media Worker** — private dog media, verification evidence, and hourly encrypted offsite PostgreSQL backups.
- **GitHub Actions / CCA-ORACLE runner** — focused CI, manual protected production app releases, hourly database backups, scheduled production integrity tests.
- **Paystack** and **Gmail SMTP** — application integrations enabled only when their respective server credentials are configured.

Public website: `https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`

R2 media gateway: `https://canecorsoancestry-edge.aighewieghosa111.workers.dev`

**Retired from production:** Northflank (former Django deployment) and Supabase (frozen historical PostgreSQL source). Neither may receive live writes or be used as an automatic fallback: after local-primary writes, a rollback to old Supabase would lose data. Older setup/migration documents are historical, not current deployment instructions.

### Releasing Django

Deploy Django to the active Oracle VM through the protected, manual `oracle-stage-django.yml` workflow on `main`. A Cloudflare Worker deployment does not replace the Oracle Django container. Check the live release marker and production smoke afterwards. Keep the hourly encrypted R2 backups running.

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
- **₦1,500** — 2–6 dogs from the same verified kennel;
- **₦1,000** — one genuine litter plus the puppies belonging to that litter.

Payment never publishes a record. The kennel/owner must already be approved, and every submitted dog or litter remains in the admin moderation queue until an administrator verifies and approves it. Litter-package eligibility is enforced server-side and conflicting litter, identity, pedigree or payment facts are routed to explainable admin review rather than silently published.

## Documentation

- `PROJECT_PLAN.md` — product plan
- `docs/OWNER_REQUIREMENTS.md` — terminology and owner requirements
- `ARCHITECTURE.md` — active technical architecture
- `docs/PRODUCTION_DEPLOYMENT.md` — current deployment/runbook
- `SKILL.md` — repository working rules
- `docs/design-reference/` — owner-approved visual references
