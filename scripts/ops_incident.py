"""Deduplicated GitHub issue alerts for trusted main-branch operational workflow results.

This watcher never touches the site, production credentials, payments or databases.
Only a completed main-branch GitHub Actions run is eligible.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "eghosa001/canecorsoancestry"
WATCHED = frozenset({
    "Production availability watch",
    "Oracle R2 backup freshness watch",
    "Oracle offsite PostgreSQL recovery integrity",
    "Production Django release attestation",
    "Production payment and policy edge probe",
    "Oracle PostgreSQL encrypted hourly backups",
    "Production data health",
    "Public page accessibility audit",
    "Security audit",
    "Oracle read-only latency diagnosis",
    "Production smoke",
})


def incident_title(name):
    return f"[CCA operational alert] {name}"


def eligible_run(event, repo):
    run = event.get("workflow_run", {})
    return (
        repo == REPOSITORY
        and run.get("name") in WATCHED
        and run.get("status") == "completed"
        and run.get("head_branch") == "main"
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("event") != "pull_request"
        and run.get("conclusion") not in (None, "skipped", "cancelled", "neutral")
    )


def api(method, path, *, payload=None):
    token = os.environ["GH_TOKEN"]
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}{path}",
        data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CCA-Operational-Incident-Watcher",
        },
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response) if response.status != 204 else {}


def active_issue(title):
    # Search a bounded number of open issues; never update unrelated incidents.
    for page in range(1, 6):
        results = api("GET", "/issues?" + urlencode({"state": "open", "per_page": 100, "page": page}))
        for entry in results:
            if "pull_request" not in entry and entry.get("title") == title:
                return entry
        if len(results) < 100:
            return None
    raise RuntimeError("Too many open issues to safely identify the operational alert.")


def sync(event, repo):
    if not eligible_run(event, repo):
        print("Ignored: not a completed, trusted main-branch monitored workflow.")
        return
    run = event["workflow_run"]
    name, conclusion = run["name"], run["conclusion"]
    title = incident_title(name)
    existing = active_issue(title)
    if conclusion == "success":
        if existing:
            api("POST", f"/issues/{existing['number']}/comments", payload={
                "body": f"Recovery verified by successful [workflow run]({run['html_url']})."
            })
            api("PATCH", f"/issues/{existing['number']}", payload={"state": "closed"})
            print(f"Closed recovered incident #{existing['number']}.")
        else:
            print(f"PASS: {name}; no active incident.")
        return
    body = (
        f"An operational check completed with **{conclusion}**.\n\n"
        f"Workflow: **{name}**\n\n"
        f"Failure evidence: {run['html_url']}\n\n"
        "Investigate the failing step and confirm the next successful run. "
        "This GitHub issue is an incident marker, **not proof that anyone received an email**. "
        "It must not be closed solely to improve a readiness score."
    )
    if existing:
        api("PATCH", f"/issues/{existing['number']}", payload={"body": body})
        print(f"Updated existing incident #{existing['number']} for {name}.")
    else:
        new = api("POST", "/issues", payload={"title": title, "body": body, "assignees": ["eghosa001"]})
        print(f"Opened operational incident #{new['number']} for {name}.")


if __name__ == "__main__":
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    sync(event, os.environ.get("GITHUB_REPOSITORY", ""))
