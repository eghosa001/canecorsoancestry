# Cane Corso Ancestry Working Rules

Use this file for future implementation work in this repository.

## Non-negotiable product rules

1. This is a **pedigree/ancestry website, not a registry**.
2. Preserve the owner-approved reference images in `docs/design-reference/`.
3. Keep the Django/Python architecture unless the owner explicitly changes it.
4. One real dog equals one canonical Dog record.
5. Repeated linebreeding ancestors are repeated pedigree positions, not duplicate dog rows.
6. Half siblings count as siblings: sharing either sire or dam is sufficient.
7. Never invent pedigree, kennel, registration, health or identity facts.
8. External registration numbers must retain their issuing authority.
9. A verification badge means evidence review, not registration by Cane Corso Ancestry.
10. Never delete a duplicate dog before all relationships and attached records have been safely merged/repointed.

## UI rules

- Follow the supplied dark charcoal/gold/ivory design language.
- Keep the pages data-rich but readable.
- Mobile pedigree layouts must restructure or scroll intentionally; do not merely shrink desktop trees.
- Dog images must remain clear and naturally framed.
- Normal users get a custom member dashboard; Django Admin is for internal moderation.
- Use **Submit/Add Dog** instead of language that implies the website registers dogs.

## Infrastructure rule

- Production infrastructure is **Render + Aiven PostgreSQL + Cloudflare R2 only**.
- Cloudflare may be used only for the R2 media gateway unless the owner explicitly changes the architecture.
- Do not reintroduce Supabase, Railway, Google Cloud Run, GitHub Pages preview, a Cloudflare application proxy, generic S3-provider branches, or migration-only infrastructure without an explicit new request.
- Prefer direct Render deployment and the existing Aiven/R2 connections over adding another service.

## Engineering rules

- Prefer server-rendered Django pages with progressive enhancement.
- Keep tests short and directly tied to the changed behavior.
- Use the smallest sensible commit set.
- Do not refactor unrelated areas during a narrow fix.
- Preserve backward-compatible URLs/data where practical.
- Run `python manage.py makemigrations --check --dry-run`, `python manage.py check`, and targeted tests before release.

## Data-change rule

For pedigree edits, verify the exact target dog and relationship before changing it. When two records may represent the same real dog, investigate and merge rather than guessing.
