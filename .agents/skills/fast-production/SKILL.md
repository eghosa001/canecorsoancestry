---
name: fast-production
description: Fast, risk-based repository execution for implementation, fixes, QA, CI, releases, deployment, UI, data, and production work.
---

# Fast Production Execution

## Goal
Finish the requested task correctly with the fewest practical reads, tool calls, commits, test runs, CI minutes, and deployments.

Repository-specific security, business, architecture, data, and release rules override this execution overlay.

## Default execution
- Classify work as micro, normal, or cross-cutting/high-risk.
- Inspect the smallest relevant surface and direct dependencies only.
- Patch the cause in one pass; avoid unrelated refactors.
- Keep tests short, behavior-specific, and tied to the changed risk.
- Run focused checks while iterating; run the full required gate once on the final candidate.
- Do not rerun a passing unchanged suite.
- Prefer one commit for small/normal work and squash large branches.
- Do not repeatedly poll CI; inspect one failure, fix it, then re-run only what failed or what changed.

## Subagents and parallel work
Use real subagents when there are at least two independent workstreams and a runner is available.
- Dispatch 2-4 non-overlapping tracks immediately.
- Good splits: backend/API vs UI, implementation vs regression tests, migration vs parity check, independent bug clusters.
- One coordinator owns integration.
- If no real subagent runner exists, check once and stop looking; batch safe tool/connector calls concurrently instead.
- Never simulate or claim subagents that were not actually used.

## Risk-based testing
- Docs/comments/agent instructions: no runtime tests.
- Copy/CSS/local navigation: one focused browser or component check.
- Data/content: schema/content validation; link/source checks only when those changed.
- API/server logic: focused unit/integration test plus type/static check.
- Auth/security/write paths: positive path plus relevant negative tests.
- Shared schema/migration/release logic: focused invariant test plus the repository's final required gate.
- Packaging/store artifacts: build only when packaging/release inputs changed or a release was requested.

## CI workflow rules
Ordinary PR/push CI must be fast and only protect merge-critical behavior.
- Keep one small required verification path where practical.
- Do not run release packaging, APK/AAB/Windows installers, full visual audits, exhaustive simulations, OCR/import/migration jobs, production seeding, or live production audits on every ordinary PR.
- Put deep/release/maintenance workflows behind manual dispatch, release tags, schedules, or narrow path filters according to their actual purpose.
- Preserve required status-check names. If branch protection requires a check, keep the workflow/job present and make irrelevant work short-circuit safely instead of skipping the required check entirely.
- Add concurrency with cancel-in-progress to PR/push workflows so stale runs stop.
- Set realistic job timeouts.
- Cache package/tool dependencies when supported.
- Prefer deterministic installs such as npm ci when a lockfile exists.
- Avoid duplicate checkout/setup/install work. Combine checks sharing the same environment unless true parallelism shortens the critical path.
- Avoid test matrices unless multiple runtime versions are genuinely supported targets.
- Upload diagnostics on failure; upload build artifacts only when the artifact is the purpose of the workflow.
- Use shallow checkout unless history is required.
- Scheduled monitoring should run only as often as the monitored condition can materially change.

## Completion
Stop when the requested behavior works, the smallest relevant regression check passes, required final checks are green, and the exact production deployment is verified only when deployment was part of the task.
