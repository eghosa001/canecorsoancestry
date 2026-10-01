#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = "FAST_PATH_POLICY_VERSION: 3"
CANONICAL_SKILL = ROOT / ".agents/skills/fast-production/SKILL.md"
REQUIRED_ADAPTERS = (
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "GEMINI.md",
    ROOT / ".github/copilot-instructions.md",
)
FORBIDDEN_INSTRUCTION_PATTERNS = (
    r"dispatch\s+2\s*[-–]\s*4\s+.*immediately",
    r"use\s+subagents\s+when\s+available",
    r"split\s+independent\s+tasks\s+immediately",
)
HEAVY_HINTS = (
    "android", "release", "export", "visual", "screenshot", "deep",
    "ocr", "migrate", "migration", "seed", "playtest", "chaos",
    "benchmark", "soak", "installer", "production-build",
)
ALLOW_BROAD = "# fast-policy: allow-broad-auto"

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def trigger_block(text: str) -> str:
    match = re.search(
        r"(?ms)^on:\s*\n(.*?)(?=^(?:permissions|concurrency|env|defaults|jobs):\s*$)",
        text,
    )
    return match.group(1) if match else ""

def trigger_body(block: str, name: str) -> str | None:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^  {re.escape(name)}\s*:(.*)$", line)
        if not match:
            continue
        collected = []
        inline = match.group(1).strip()
        if inline:
            collected.append(inline)
        for next_line in lines[index + 1:]:
            if re.match(r"^  \S", next_line):
                break
            collected.append(next_line)
        return "\n".join(collected)
    return None

def filtered(body: str | None) -> bool:
    if body is None:
        return False
    return bool(re.search(r"(?m)^\s{4}(?:paths|paths-ignore|tags|tags-ignore)\s*:", body))

def broad_pull(block: str) -> bool:
    body = trigger_body(block, "pull_request")
    return body is not None and not filtered(body)

def broad_main_push(block: str) -> bool:
    body = trigger_body(block, "push")
    if body is None or filtered(body):
        return False
    branches = re.search(r"(?m)^\s{4}branches\s*:\s*(.*)$", body)
    if branches:
        return "main" in branches.group(1)
    return True

def is_heavy(path: Path, text: str) -> bool:
    head = "\n".join(text.splitlines()[:25])
    haystack = f"{path}\n{head}".lower()
    return any(hint in haystack for hint in HEAVY_HINTS)

def inspect_instructions(errors: list[str]) -> None:
    if not CANONICAL_SKILL.exists():
        errors.append(f"Missing canonical skill: {CANONICAL_SKILL.relative_to(ROOT)}")
        return
    skill = read(CANONICAL_SKILL)
    if POLICY_VERSION not in skill:
        errors.append("Canonical fast-production skill is not policy version 3.")
    if "DEFAULT: ONE DIRECT PATH, ZERO SUBAGENTS" not in skill:
        errors.append("Canonical skill must keep the single-path/zero-subagent default.")
    instruction_files = [CANONICAL_SKILL, *REQUIRED_ADAPTERS]
    root_skill = ROOT / "SKILL.md"
    if root_skill.exists():
        instruction_files.append(root_skill)
    for path in instruction_files:
        if not path.exists():
            errors.append(f"Missing agent instruction adapter: {path.relative_to(ROOT)}")
            continue
        text = read(path)
        for pattern in FORBIDDEN_INSTRUCTION_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                errors.append(f"{path.relative_to(ROOT)} reintroduces fan-out behavior: {pattern}")
    for path in REQUIRED_ADAPTERS:
        if path.exists() and ".agents/skills/fast-production/SKILL.md" not in read(path):
            errors.append(f"{path.relative_to(ROOT)} must point to the canonical fast-production skill.")

def inspect_workflows(errors: list[str]) -> None:
    workflow_dir = ROOT / ".github/workflows"
    if not workflow_dir.exists():
        return
    broad_auto = 0
    for path in sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))):
        text = read(path)
        block = trigger_block(text)
        if not block:
            continue
        broad = broad_pull(block) or broad_main_push(block)
        if broad:
            broad_auto += 1
            if "cancel-in-progress: true" not in text:
                errors.append(f"{path.relative_to(ROOT)} is broad automatic CI without stale-run cancellation.")
            if "timeout-minutes:" not in text:
                errors.append(f"{path.relative_to(ROOT)} is broad automatic CI without a bounded timeout.")
        if broad and is_heavy(path, text) and ALLOW_BROAD not in text:
            errors.append(
                f"{path.relative_to(ROOT)} is a heavy workflow running broadly. "
                f"Make it manual/path/tag scoped, or document the deployment exception with '{ALLOW_BROAD}'."
            )
        if broad and "matrix:" in text and ALLOW_BROAD not in text:
            errors.append(
                f"{path.relative_to(ROOT)} uses a broad automatic matrix. "
                "Use targeted jobs or document the rare exception."
            )
    if broad_auto > 3:
        errors.append(f"Repository has {broad_auto} broad automatic workflows; keep at most 3.")
    guard_workflow = workflow_dir / "fast-policy.yml"
    if not guard_workflow.exists():
        errors.append("Missing .github/workflows/fast-policy.yml.")
    elif "scripts/fast_path_guard.py" not in read(guard_workflow):
        errors.append("Fast Policy Guard no longer runs scripts/fast_path_guard.py.")

def main() -> int:
    errors: list[str] = []
    inspect_instructions(errors)
    inspect_workflows(errors)
    if errors:
        print("Fast-path policy violations:")
        for item in errors:
            print(f" - {item}")
        return 1
    print("Fast-path policy OK: shortest path first; zero subagents by default; heavy CI constrained.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
