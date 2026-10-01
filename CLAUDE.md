# Mandatory Fast-Path Directive

Before implementation, investigation, QA, CI, deployment, or repository maintenance, read and follow:

`.agents/skills/fast-production/SKILL.md`

**Default to one direct implementation path and zero subagents.** Add a subagent only when the skill's subagent gate is fully satisfied and parallelism is expected to reduce wall-clock time. Do not weaken or bypass `Fast Policy Guard`.

# Claude Adapter
Repository-specific instructions still apply after the canonical fast-production policy.
