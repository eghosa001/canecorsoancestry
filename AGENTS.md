# Mandatory Fast-Path Directive

Before implementation, investigation, QA, CI, deployment, or repository maintenance, read and follow:

`.agents/skills/fast-production/SKILL.md`

**Default to one direct implementation path and zero subagents.** Add a subagent only when the skill's subagent gate is fully satisfied and parallelism is expected to reduce wall-clock time. Do not weaken or bypass `Fast Policy Guard`.

# Repository Agent Instructions

For implementation, fixes, QA, CI, release, deployment, UI/UX, data, and production work, always read and follow:

`.agents/skills/fast-production/SKILL.md` and the repository-specific `SKILL.md`

Use the shortest safe execution path. Use real subagents for genuinely independent tracks when available; otherwise batch safe work. Keep tests focused and short, avoid duplicate CI work, and run heavy/release validation only when its purpose requires it.

## Permanent Safari compatibility rule

Treat iPhone/iPad Safari (WebKit) as a first-class target for every future relevant UI, form, navigation, media, or JavaScript change. Preserve Safari-safe input font sizes (at least 16px for touch inputs), safe-area spacing, natural image framing, native document/photo uploads, sticky header/pedigree scrolling, and touch menu/autocomplete behavior. Changes affecting those surfaces must pass the narrow, path-scoped Safari WebKit smoke in `.github/workflows/safari-compat.yml`; do not run an unrelated browser matrix. This rule does not weaken the mandatory fast-path CI policy.
