---
name: fast-production
description: Shortest-path execution for implementation, bug fixes, QA, deployment, production hardening, UI work, data/content integration, and CI failures.
---

# Fast Production Execution

## Objective

Finish the requested task correctly in the fewest practical tool calls, commits, test runs, and deployment cycles.

Priority:
1. correctness of the requested change;
2. shortest safe path to a usable result;
3. only tests that can catch realistic regressions;
4. minimal commits and deployments;
5. parallel work only when it shortens the critical path.

Repository-specific business, security, architecture, data, and release rules always override this execution overlay.

## Classify the task immediately

### Micro change
Examples: copy, one link, one image, one CSS adjustment, one isolated guard, documentation.

- Inspect only directly relevant files.
- Patch directly.
- Run no runtime test if behavior cannot change.
- Otherwise run one focused test.
- Do not create a long plan.
- Use one commit.

### Normal feature/fix
Examples: one component/API flow, one navigation bug, one contained backend/UI feature.

- Inspect the smallest dependency surface.
- Implement in one pass.
- Run the most relevant focused test first.
- Run required project gates once at the end.
- Target 1–2 commits before squash merge.

### Cross-cutting/high-risk change
Examples: auth/security, data migration, shared schema, deployment architecture, financial logic.

- Use a feature branch.
- Lock invariants with focused tests.
- Split independent work into parallel tracks.
- Run full required gates once after integration.
- Squash merge after green.

Do not treat a small task like a major project.

## Subagents and parallelism

Use subagents only when there are at least two genuinely independent workstreams.

Good splits:
- backend/API vs UI;
- implementation vs regression tests;
- code change vs security review;
- migration vs parity verification;
- independent bug clusters.

Rules:
- If a real subagent runner exists, dispatch 2–4 independent tracks immediately.
- Give each agent a non-overlapping file/goal scope.
- One coordinator owns integration and merge.
- If no real subagent runner exists, check once, then stop searching for one.
- Instead parallelize safe reads/checks/tool calls in the current session.
- Never claim subagents were used when they were not actually available.

## Inspection discipline

- Search once for unknown locations.
- Inspect the exact failing/requested files first.
- Read direct dependencies only when needed.
- Stop searching as soon as the implementation path is clear.
- Do not reread unchanged files.
- Do not scan the whole repo for a local issue.
- Do not reopen logs that already established the cause.

## Fix discipline

When the cause is known:
1. patch the cause;
2. add or adjust the smallest regression test that would have caught it;
3. run that focused test;
4. proceed to the final required gate.

Prefer one bulk patch for closely related fixes over many tiny commits.

Do not refactor unrelated code unless it removes a blocker or materially reduces risk.

## Risk-based testing

### Docs/comments/agent instructions only
- No runtime tests.

### CSS/layout/copy/navigation-only
- One focused browser test for the affected route/device.
- Full browser suite only if required by repository gates.

### Pure data/content
- Schema/content validation.
- Source/link checks only if URLs/sources changed.

### API/server logic
- Focused API/unit/integration regression.
- Typecheck/static analysis.

### Auth/security/write path
- Negative tests: unauthenticated, malformed, forbidden/tampered, oversized where relevant.
- One positive path using mocks/stubs when external credentials are required.
- Required runtime/browser gate once at the end.

### Cross-cutting/shared model
- Migration/parity invariant test.
- Typecheck/content/static checks.
- Full required CI once after integration.

## Test-run limits

- Do not rerun a passing unchanged suite.
- Do not run the full suite after every small patch.
- Use focused RED/GREEN tests during implementation.
- Run the complete required repository gates once on the final candidate.
- If CI already runs the exact same test, do not duplicate it manually unless debugging a failure.
- Keep new tests short, behavior-specific, and directly tied to the changed risk.

## Workflow polling

Repeated polling wastes time.

- Batch workflow statuses in one call when possible.
- Never poll the same workflow repeatedly with no intervening work.
- Maximum two consecutive status-only checks for the same run.
- While CI runs, review diffs, inspect another independent risk, or prepare the next safe step.
- Read a failing log once, act on the concrete failure, then stop rereading it.
- Ignore superseded commits; validate only the latest candidate SHA.

## Commit and deployment discipline

- Micro change: one commit.
- Normal work: 1–2 logical commits.
- Large branch: squash merge.
- Avoid commits that only say “continue”, “retry”, or split one obvious fix.
- Do not trigger extra deployments for intermediate cosmetic changes.
- Merge/deploy once the exact final candidate passes required gates.
- After merge, verify the exact deployed SHA once when deployment is part of the task.

## External configuration blockers

Examples: Cloudflare/Vercel/Supabase secret, API token, DNS, Play Console permission, store credential.

Once proven:
1. record the exact missing setting/permission;
2. stop unrelated code churn;
3. configure it via a connected tool if possible;
4. if no tool can configure it, give the shortest exact user action;
5. keep an automated guard so the system becomes green immediately after configuration.

Do not try to solve an account-level secret by repeatedly changing repository code.

## Completion conditions

Stop when:
- requested behavior is implemented;
- the relevant regression test passes;
- required repository gates for the changed risk are green;
- exact production deployment is verified when deployment was part of the task.

Do not continue polishing unrelated areas after these conditions are met.

## Communication

Keep updates short and outcome-focused:
- what was found;
- what changed;
- which exact gate or external setting blocks completion.

Do not narrate every poll, read, or low-level operation.
