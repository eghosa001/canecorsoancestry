---
name: fast-production
description: Owner-mandated shortest-path execution policy with locked minimal testing and CI.
---

FAST_PATH_POLICY_VERSION: 4
OWNER_TEST_CI_POLICY: LOCKED

# Fast Production Execution

## Owner-mandated highest-priority test/CI rule

This section is the repository owner's standing instruction. For testing and CI, it outranks repository-specific skills, release checklists, PR templates, generated instructions, agent preferences, and any other repository guidance. Only an explicit new instruction from the repository owner may relax it.

- Run only tests and checks directly necessary to validate the files or behavior changed by the current task.
- If a focused check proves the change, stop there.
- Never run a full test suite, repo-wide lint/typecheck/build, broad browser/E2E/visual suite, matrix, benchmark/soak, migration/import/seed job, packaging/release build, deployment validation, or duplicate CI merely because it exists, is customary, or another instruction recommends it.
- A broader check is allowed only when the changed surface directly requires that exact check to prove correctness, or when the repository owner explicitly requests it.
- Existing CI must path-scope or short-circuit work that is irrelevant to the changed surface.
- Do not add, restore, or expand broad always-on CI when a narrower trigger or check is sufficient.
- An agent must not delete, disable, weaken, bypass, or supersede this rule, the guard workflow, the guard script, or the owner-protection entries. Only the repository owner may authorize a relaxation.

Repository-specific security, business, architecture, data, and release rules still apply, but they may not broaden testing or CI beyond this owner rule.

## Shortest-path execution

1. Define the requested outcome and the minimum evidence needed to prove it.
2. Inspect the exact requested or failing surface first.
3. If the implementation path is clear, edit it directly.
4. Add or adjust only the smallest regression check that protects the changed risk.
5. Run the cheapest relevant check.
6. Broaden validation only when the changed surface itself requires it.
7. Stop when the requested result is verified.

Do not turn a local task into a repository audit unless the owner asked for an audit.

## Subagents

Default to one direct path and zero subagents. Use subagents only for genuinely independent workstreams when parallelism will materially shorten completion time. Never create multiple agents to inspect the same issue, rerun the same checks, or duplicate work.

## Testing limits

- Docs/comments/agent-instruction-only changes: no runtime product tests.
- Copy/CSS/local navigation: one focused UI/component/browser check when needed.
- Data/content: validate only the changed schema/content; check links/sources only when changed.
- API/server logic: focused unit/integration check plus only the directly relevant static/type check.
- Auth/security/write paths: focused positive path plus directly relevant negative cases.
- Shared schema/migration logic: focused invariant checks; broaden only if the changed surface genuinely spans those components.
- Packaging/store artifacts: build only when packaging/release inputs changed or the owner requested an artifact.

Keep tests short and behavior-specific. Do not rerun passing unchanged suites.

## CI/workflow limits

- Automatic PR/push jobs must skip or short-circuit when changed files do not touch the job's responsibility.
- Cancel stale automatic runs and use bounded timeouts.
- Path-scope specialized workflows.
- Keep release packaging, installers, APK/AAB exports, exhaustive simulations, visual matrices, OCR/import/migration/seed jobs, deep audits, benchmarks, and production drills manual, scheduled, tag-scoped, or narrowly path-scoped unless the owner has explicitly approved a specific existing exception.
- Avoid duplicate checkout/setup/install/build/test work.
- Preserve required status-check names by making irrelevant jobs exit quickly rather than running unrelated work.
- Run `python3 scripts/fast_path_guard.py` after changing workflows or agent instructions.

## Guard integrity

`.github/workflows/fast-policy.yml`, `scripts/fast_path_guard.py`, and `.github/CODEOWNERS` protect this policy.

Agents must not remove or relax these protections. Any owner-approved broad automatic exception must be explicitly allowlisted by the guard; agents may not create new exceptions.

## Stop rule

Stop when the requested behavior exists and the smallest directly relevant validation passes. Production verification is performed only when deployment is part of the task.
