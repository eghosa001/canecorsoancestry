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
11. New dog/litter publication is **pay-to-submit, never pay-to-publish**: ₦500 for one dog, ₦1,500 for 2–4 dogs, or ₦200 for one litter plus its puppies.
12. A Paystack payment only creates submission entitlement. An administrator must still verify and approve every dog/litter before it becomes public.
13. A kennel must be administrator-verified and the submitting member must be an approved kennel owner/editor before a paid dog/litter package can be used.

## UI rules

- Follow the supplied dark charcoal/gold/ivory design language.
- Keep pages data-rich but readable.
- Mobile pedigree layouts must restructure or scroll intentionally; do not merely shrink desktop trees.
- Dog images must remain clear and naturally framed.
- Normal users get a custom member dashboard; Django Admin is for internal moderation.
- Use **Submit/Add Dog** instead of language that implies the website registers dogs.

## Infrastructure rule

The current production stack is:

- Cloudflare Workers public site edge: `canecorsoancestry-site-edge.aighewieghosa111.workers.dev`
- Northflank Django origin
- Supabase PostgreSQL
- Cloudflare R2 media gateway/storage

No custom domain is currently configured. Do not add a custom domain or another hosting/database provider unless the owner explicitly requests it.

Keep private/authenticated routes uncached at the Cloudflare site edge.

## Engineering rules

- Prefer server-rendered Django pages with progressive enhancement.
- Keep tests short and directly tied to the changed behavior.
- Use the smallest sensible commit set.
- Do not refactor unrelated areas during a narrow fix.
- Preserve backward-compatible URLs/data where practical.
- Run only the checks directly required by the changed surface.

## Data-change rule

For pedigree edits, verify the exact target dog and relationship before changing it. When two records may represent the same real dog, investigate and merge rather than guessing.
