---
name: fast-production
description: Mandatory shortest-path execution policy for implementation, fixes, QA, CI, release, deployment, UI, data, and production work.
---

FAST_PATH_POLICY_VERSION: 3

# Fast Production Execution

## Non-negotiable default

**DEFAULT: ONE DIRECT PATH, ZERO SUBAGENTS.**

Start with the smallest direct implementation that can produce and verify the requested result. Do not fan out work merely because parallel tools or agents exist.

Repository-specific security, business, architecture, data, and release rules still apply.

## Shortest-path algorithm

1. State the exact requested outcome and the minimum evidence that proves it.
2. Inspect the exact failing/requested surface first.
3. If the implementation path is clear, edit it immediately; stop exploring alternatives.
4. Add or adjust only the smallest regression check that protects the changed risk.
5. Run the cheapest relevant check first.
6. Run a broader required gate once only when the changed risk or repository rules require it.
7. Stop when the requested result is verified.

Do not restart discovery after the cause is known. Do not turn a local task into a repository audit unless the user asked for an audit.

## Subagent gate

Subagents are opt-in, not a default. Use them only when **all** of these are true:
- there are at least two genuinely independent workstreams;
- the workstreams do not compete for the same files or decisions;
- each workstream is substantial enough to justify coordination overhead;
- parallel execution is expected to shorten wall-clock time versus one direct path;
- one coordinator can integrate the results without repeating the work.

If any condition is false, use no subagents.

Additional limits:
- Default maximum: 2 subagents.
- Use 3 only for an explicitly requested broad audit/release or three clearly independent high-risk domains.
- Never create multiple agents to inspect the same problem, rerun the same tests, compare equivalent implementations, or “be thorough.”
- Never search repeatedly for a subagent runner. If unavailable, continue directly.
- Safe independent tool reads may be batched without creating agents.

## Investigation limits

- Prefer direct file/path/log access when the location is known.
- Search once for an unknown location; refine only if the first search is insufficient.
- Read direct dependencies only when needed.
- Do not reread unchanged files or logs.
- Do not create plan/status/audit documents unless requested.
- Do not add a dependency, abstraction, service, branch, or workflow when the existing path can solve the task.
- When the user says “continue,” resume from the current state instead of re-auditing completed work.

## Testing limits

- Docs/comments/agent-instruction-only changes: no runtime product tests.
- Copy/CSS/local navigation: one focused UI/component/browser check.
- Data/content: validate the changed schema/content; check links/sources only when they changed.
- API/server logic: focused unit/integration check plus relevant static/type check.
- Auth/security/write paths: focused positive path plus relevant negative cases.
- Shared schema/migration/release logic: focused invariant check plus the final required gate.
- Packaging/store artifacts: build only when packaging/release inputs changed or a release was requested.

Keep new tests short and behavior-specific. Do not rerun a passing unchanged suite. Do not run the full suite after every patch.

## CI/workflow limits

Ordinary PR/push CI must protect merge-critical behavior, not reproduce release certification.
- Cancel stale automatic runs.
- Set bounded timeouts.
- Path-scope specialized workflows.
- Keep release packaging, installers, APK/AAB exports, exhaustive simulations, visual matrices, OCR/import/migration/seed jobs, and deep audits manual, tag-scoped, scheduled, or narrowly path-scoped.
- Avoid duplicate install/build/test work across workflows.
- Prefer one environment setup for checks that can run sequentially cheaply.
- Upload diagnostics on failure; upload build artifacts only when the artifact is the purpose.
- Preserve required status-check names.
- Run `python3 scripts/fast_path_guard.py` after changing workflows or agent instructions.

## Guard integrity

`.github/workflows/fast-policy.yml` and `scripts/fast_path_guard.py` enforce this policy.

Do not delete, disable, weaken, skip, or bypass the guard merely to make CI pass. Fix the underlying workflow/instruction violation instead. A broad automatic heavy workflow is allowed only when it is genuinely required for deployment and contains a narrow documented `# fast-policy: allow-broad-auto` exception.

## Commits, deployments, and polling

- Small/normal task: prefer one cohesive commit.
- Larger branch: keep commits logical and squash when appropriate.
- Do not commit merely to retrigger CI.
- Do not deploy intermediate cosmetic states.
- Do not poll unchanged workflow status repeatedly.
- Inspect a failing log once, act on the concrete failure, then rerun only the relevant check.
- Ignore superseded runs/commits.

## Stop rule

Stop work when:
- the requested behavior exists;
- the smallest relevant regression check passes;
- required final gates for the changed risk are green;
- production is verified only when deployment was part of the request.

Do not continue polishing unrelated areas after these conditions are met.
