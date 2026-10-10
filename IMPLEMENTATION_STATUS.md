# Cane Corso Ancestry — Implementation Status

Updated: 10 October 2026

## Current state

Cane Corso Ancestry is a production Django pedigree/ancestry platform with public search, dog profiles, kennel and litter views, pedigree analysis, virtual mating, member workspaces, moderation, duplicate handling and source-aware data workflows.

The active production path is:

`Cloudflare Workers site edge → private Cloudflare VPC → Oracle VM Django/Gunicorn → Oracle-local PostgreSQL 17`

Uploaded media is stored in Cloudflare R2 and served through the dedicated R2 media Worker.

Public site:

`https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev`

No custom domain is configured.

## Product guardrails

- Pedigree/ancestry platform, **not a registry**.
- One real dog maps to one canonical Dog record.
- Repeated pedigree positions do not create duplicate dogs.
- Half siblings are derived from either shared sire or shared dam.
- Missing pedigree, kennel, registration, health and identity facts remain missing rather than being invented.
- External registration numbers retain their issuing authority.
- Verification means evidence review, not registration by Cane Corso Ancestry.

## Implemented product areas

- public dog and kennel search;
- dog profiles, parents, siblings and offspring;
- 4/6/8/10-generation pedigree views;
- repeated-ancestor and common-ancestor analysis;
- COI and virtual mating;
- member dashboard and kennel workspaces;
- moderated dog, litter, document and correction submissions;
- dispute/review cases and moderation audit history;
- safe duplicate detection and merge tooling;
- Cloudflare R2 media delivery;
- responsive public/member UI based on the retained design references.

## Active infrastructure

- **Cloudflare Workers site edge** — public endpoint, cache and warm-up layer;
- **Oracle VM** — Django/Gunicorn production origin and GitHub Actions runner;
- **Oracle-local PostgreSQL 17** — canonical authoritative live database; Supabase is a frozen old source and must not receive production writes;
- **Cloudflare R2** — durable media storage.

Northflank is retired, and reconnecting it to Supabase would risk stale writes. Current infrastructure documentation is maintained in `ARCHITECTURE.md` and `docs/PRODUCTION_DEPLOYMENT.md`.

## Acceptance baseline

Visual changes should continue to be checked against:

- `docs/design-reference/public-pedigree-reference.jpg`
- `docs/design-reference/member-dashboard-reference.jpg`

Data changes must preserve canonical dog identity and existing relationships.
