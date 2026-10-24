"""Consolidate QA matrix evidence without inventing passed coverage."""
import html
import json
import re
from pathlib import Path

SOURCE = Path("artifacts/collected")
OUT = Path("artifacts/qa-final")
OUT.mkdir(parents=True, exist_ok=True)
EXPECTED = {
    "chromium": {
        "public_search_navigation_responsive", "email_signup_verification_password_reset",
        "dog_draft_photo_database", "dog_draft_invalid",
        "image_upload_rejection_review", "cross_account_dog_authorization",
        "kennel_editor_permissions", "staff_isolation", "django_admin_synthetic_dog",
        "document_certificate_evidence_review", "dog_correction_pending_canonical_integrity",
        "pedigree_csv_and_virtual_mating", "staff_private_dog_create_with_image",
        "kennel_claim_with_private_certificate", "health_evidence_pending_moderation",
        "saved_pairing_create_delete", "paystack_unconfigured_safety",
        "private_dog_admin_edit_delete",
    },
    "firefox": None,
    "webkit": None,
}
EXPECTED["firefox"] = EXPECTED["chromium"]
EXPECTED["webkit"] = EXPECTED["chromium"]
issues = []
all_cases = []
for browser, required in EXPECTED.items():
    path = SOURCE / f"cases-{browser}.json"
    if not path.exists():
        issues.append(f"MISSING browser report: {browser}")
        continue
    cases = json.loads(path.read_text())
    all_cases.extend(cases)
    observed = {case["name"] for case in cases}
    if observed != required:
        issues.append(f"{browser}: missing cases {sorted(required - observed)}, unexpected {sorted(observed - required)}")
    for case in cases:
        if case["status"] != "PASS":
            issues.append(f"{browser} {case['name']}: {case['status']} — {case.get('error', '')}")

backend = {}
for app in ("accounts", "registry", "pedigrees", "core"):
    file = SOURCE / f"backend-{app}.log"
    if not file.exists():
        issues.append(f"MISSING backend module results: {app}")
        backend[app] = "BLOCKED"
        continue
    log = file.read_text(errors="replace")
    good = re.search(r"Ran \d+ tests?", log) and re.search(r"^OK(?: \(skipped=\d+\))?$", log, re.M)
    backend[app] = "PASS" if good else "FAIL"
    if not good:
        issues.append(f"Backend module failed or did not complete: {app}")

legacy = SOURCE / "role-browser-audit" / "summary.json"
if not legacy.exists():
    other = SOURCE / "summary.json"
    legacy = other if other.exists() else legacy
if not legacy.exists():
    issues.append("MISSING existing role browser audit results")
    legacy_data = {"passed_count": 0, "failed_count": 0}
else:
    legacy_data = json.loads(legacy.read_text())
    if legacy_data.get("failed_count") or legacy_data.get("passed_count", 0) == 0:
        issues.append("Existing role browser audit failed or contains no passing scenarios")

inventory_file = SOURCE / "feature-inventory.json"
inventory = json.loads(inventory_file.read_text()) if inventory_file.exists() else None
if inventory is None:
    issues.append("MISSING dynamic Django URL/admin inventory")

phases = [
    "Django routes, forms and permission discovery", "Isolated database and synthetic identities",
    "Guest functionality", "Registration and password recovery", "Member dashboard and ownership",
    "Dog creation, editing and deletion", "Pedigrees and COI parity", "Virtual mating and research",
    "Kennels, litters and puppies", "Paystack checkout, callbacks and webhook security",
    "Moderator approval workflows", "Senior moderator permissions", "Super Admin and Django Admin",
    "Health, DNA, photo and document evidence", "Responsive layouts and accessibility",
    "Error handling and security", "Performance and data integrity", "Route/action coverage reconciliation",
    "Repair and regression verification", "Evidence, reports and release status",
]
# A phase is *not* passed merely because some tests may be relevant to it.
# Connect actual results only to named browser test journeys.
phase_evidence = {
    1: ["feature-inventory.json"], 2: ["isolated SQLite, mail and media fixture jobs"],
    3: ["public_search_navigation_responsive"], 4: ["email_signup_verification_password_reset"],
    5: ["cross_account_dog_authorization"], 6: ["dog_draft_photo_database", "dog_draft_invalid", "dog_correction_pending_canonical_integrity", "staff_private_dog_create_with_image"],
    7: ["pedigree_csv_and_virtual_mating", "backend-pedigrees.log", "backend-registry.log"],
    8: ["pedigree_csv_and_virtual_mating", "saved_pairing_create_delete"],
    9: ["kennel_claim_with_private_certificate"],
    10: ["paystack_unconfigured_safety", "backend-accounts.log"],
    11: ["existing role browser audit"],
    13: ["django_admin_synthetic_dog", "private_dog_admin_edit_delete"],
    14: ["image_upload_rejection_review", "document_certificate_evidence_review", "health_evidence_pending_moderation"],
    15: ["public_search_navigation_responsive"], 16: ["staff_isolation", "cross_account_dog_authorization"],
    18: ["feature-inventory.json"], 20: ["junit-*.xml", "cases-*.json", "Playwright traces"],
}
phase_report = [
    {"phase": i, "objective": name,
     "evidence_available": phase_evidence.get(i, []),
     "complete": False,
     "status": "NOT TESTED IN FULL",
     "note": "Some evidence exists, but phase-level completeness requires all detailed actions to be mapped and exercised."}
    for i, name in enumerate(phases, start=1)
]

report = {
    "status": "FAIL" if issues else "PARTIAL COVERAGE — automated gates passed",
    "passed_browser_cases": sum(x["status"] == "PASS" for x in all_cases),
    "total_browser_cases": len(all_cases),
    "backend_modules": backend,
    "legacy_role_cases": legacy_data,
    "discovered_routes": len(inventory["routes"]) if inventory else None,
    "discovered_admin_models": len(inventory["admin_models"]) if inventory else None,
    "all_routes_tested": False,
    "all_20_phases_completed": False,
    "unverified_feature_notice": "Routes and role actions not evidenced by tests remain NOT TESTED, not PASS.",
    "issues": issues,
    "phases": phase_report,
}
(OUT / "dashboard.json").write_text(json.dumps(report, indent=2))
rows = "".join(
    "<tr><td>" + html.escape(c.get("browser", "")) + "</td><td>" +
    html.escape(c["role"]) + "</td><td>" + html.escape(c["name"]) +
    "</td><td>" + html.escape(c["status"]) + "</td></tr>"
    for c in all_cases
)
phase_rows = "".join(
    f"<tr><td>{p['phase']}</td><td>{html.escape(p['objective'])}</td>"
    f"<td>{html.escape(', '.join(p['evidence_available']))}</td>"
    f"<td>{html.escape(p['status'])}</td></tr>" for p in phase_report
)
(OUT / "dashboard.html").write_text(
    "<!doctype html><meta charset='utf-8'><title>Cane Corso comprehensive QA</title>"
    "<h1>Full QA audit result: " + html.escape(report["status"]) + "</h1>"
    f"<p>Passed browser journeys: {report['passed_browser_cases']}/{report['total_browser_cases']}</p>"
    f"<p>Backend module results: {html.escape(str(backend))}</p>"
    "<p>This report does not equate loading a route with validating every function.</p>"
    "<h2>Critical issues / missing runs</h2><pre>" + html.escape("\n".join(issues)) + "</pre>"
    "<h2>Actual browser outcomes</h2><table border='1'><tr><th>Browser</th><th>Role</th>"
    "<th>Scenario</th><th>Status</th></tr>" + rows + "</table>"
    "<h2>Original 20-phase specification</h2><table border='1'><tr><th>Phase</th>"
    "<th>Scope</th><th>Available evidence</th><th>Completeness</th></tr>" +
    phase_rows + "</table>"
)
print(json.dumps({k: v for k,v in report.items() if k not in ("legacy_role_cases","phases")}, indent=2))
if issues:
    raise SystemExit(1)
