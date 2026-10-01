# Mandatory Fast-Path Directive

Before implementation, investigation, QA, CI, deployment, or repository maintenance, read and follow:

`.agents/skills/fast-production/SKILL.md`

**Default to one direct implementation path and zero subagents.** Add a subagent only when the skill's subagent gate is fully satisfied and parallelism is expected to reduce wall-clock time. Do not weaken or bypass `Fast Policy Guard`.

# Repository Agent Instructions

For implementation, fixes, QA, CI, release, deployment, UI/UX, data, and production work, always read and follow:

`.agents/skills/fast-production/SKILL.md` and the repository-specific `SKILL.md`

Use the shortest safe execution path. Use real subagents for genuinely independent tracks when available; otherwise batch safe work. Keep tests focused and short, avoid duplicate CI work, and run heavy/release validation only when its purpose requires it.
