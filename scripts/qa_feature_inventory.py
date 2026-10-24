"""Enumerate every Django endpoint and admin model with explicit coverage state.

NOT_TESTED is intentional: a route inventory must not be mistaken for successful
browser execution. CI attaches this machine-readable report to each run.
"""
import json
import os
from pathlib import Path

import django
django.setup()

from django.contrib import admin
from django.urls import URLPattern, URLResolver, get_resolver

out = Path(os.environ.get("CCA_QA_REPORT_ROOT", "artifacts/full-qa"))
out.mkdir(parents=True, exist_ok=True)

def walk(patterns, prefix=""):
    for item in patterns:
        if isinstance(item, URLResolver):
            yield from walk(item.url_patterns, prefix + str(item.pattern))
        elif isinstance(item, URLPattern):
            route = prefix + str(item.pattern)
            if route.startswith("admin/"):
                role = "super_admin"
            elif route.startswith("member/moderation/"):
                role = "moderator_senior_admin"
            elif route.startswith("member/") or route.startswith("dashboard/"):
                role = "member"
            else:
                role = "guest_or_authenticated"
            yield {
                "route": route, "name": str(item.name or ""),
                "role_scope": role,
                "status": "NOT_TESTED",
                "reason": "Discovery only: browser and backend evidence is reported separately",
            }

routes = sorted(walk(get_resolver().url_patterns), key=lambda x: x["route"])
admin_models = [
    {"model": model._meta.label, "admin_class": klass.__class__.__name__, "status": "NOT_TESTED"}
    for model, klass in sorted(admin.site._registry.items(), key=lambda item: item[0]._meta.label)
]
report = {"routes": routes, "admin_models": admin_models,
          "counts": {"routes_discovered": len(routes), "admin_models_discovered": len(admin_models),
                     "routes_claimed_passed_without_evidence": 0}}
(out / "feature-inventory.json").write_text(json.dumps(report, indent=2))
with (out / "feature-inventory.md").open("w") as f:
    f.write("# Discovered route and admin-model inventory\n\n")
    f.write("Discovery is not proof of execution. Unmapped actions remain NOT_TESTED.\n\n")
    f.write("| Route | Name | Role scope | Status |\n|---|---|---|---|\n")
    for r in routes:
        f.write(f"| \`{r['route'].replace('|', '&#124;')}\` | {r['name']} | {r['role_scope']} | {r['status']} |\n")
    f.write("\n## Django Admin registered models\n\n")
    for m in admin_models:
        f.write(f"- {m['model']} — {m['status']}\n")
print(json.dumps(report["counts"]))
