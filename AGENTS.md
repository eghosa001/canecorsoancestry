# Repository Agent Instructions

For implementation, bug fixing, QA, deployment, production hardening, UI/UX, content/data integration, and CI work, read and follow:

`.agents/skills/fast-production/SKILL.md`

Use the shortest safe execution path:
- inspect only the relevant surface;
- use subagents only when genuinely parallel work exists and a real runner is available;
- otherwise parallelize safe tool calls;
- run only risk-relevant focused tests during implementation;
- run full required gates once on the final candidate;
- avoid repeated CI polling and unnecessary commits/deployments;
- stop code churn once an external configuration blocker is conclusively identified.

Repository-specific business, security, architecture, data, and release rules remain authoritative.
