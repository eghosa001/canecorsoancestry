#!/usr/bin/env python3
"""Detect provider/route drift against infra/active-services.json (stdlib only)."""
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
registry = json.loads((ROOT / "infra/active-services.json").read_text())
active = {service["id"]: service for service in registry["services"]}
retired = {service["id"] for service in registry["retired"]}
assert {"cloudflare-site-edge", "oracle-django", "oracle-local-postgres", "r2-media", "github-actions"} <= active.keys()
assert {"northflank", "supabase"} <= retired
for service in registry["services"]:
    for name in ("source", "workflow"):
        if name in service:
            assert (ROOT / service[name]).is_file(), (service["id"], name)

wrangler = tomllib.loads((ROOT / "wrangler.site.toml").read_text())
vars_ = wrangler["vars"]
assert wrangler["name"] == "canecorsoancestry-site-edge"
assert vars_["ORIGIN_URL"] == "http://127.0.0.1:18080"
assert vars_["ORIGIN_TRANSPORT"] == "private-vpc"
assert len(wrangler["vpc_services"]) == 1
assert wrangler["vpc_services"][0]["binding"] == "ORIGIN_VPC"
assert wrangler["vpc_services"][0]["service_id"] == "01a11f0b-aa4d-7fd1-840b-8d7c0221f481"

edge = (ROOT / ".github/workflows/cloudflare-site-edge.yml").read_text()
assert "Provision Northflank origin" not in edge
assert 'test "$mode" = "oracle"' in edge
assert "workflow_run:" not in edge
assert "APP_RELEASE_SHA:" not in edge
assert "http://127.0.0.1:18080" in edge

health = (ROOT / ".github/workflows/production-data-health.yml").read_text()
assert "runs-on: [self-hosted, linux, arm64, cca-oracle]" in health
assert '"database_backend"] == "oracle-local"' in health
assert "discover_supabase_session_pooler" not in health
assert "SUPABASE_DATABASE_URL" not in health

oracle = (ROOT / "scripts/oracle_runner/oracle_settings.py").read_text()
assert "config.settings.northflank" not in oracle
assert "CloudflareR2GatewayStorage" in oracle

removed = (
    "provision-northflank.yml",
    "oracle-local-postgres-production.yml",
    "oracle-local-postgres-shadow.yml",
    "oracle-prepare-db-freeze.yml",
    "oracle-production-cutover.yml",
    "oracle-public-card-rollout.yml",
    "oracle-temp-env-preflight.yml",
    "oracle-private-vpc.yml",
    "oracle-capacity-rollout.yml",
    "oracle-db-route-probe.yml",
    "oracle-pg-bridge-preflight.yml",
    "oracle-r2-db-backup.yml",
    "backfill-canecorso-metadata.yml",
    "refresh-canecorso-latest.yml",
    "import-canecorso-archive.yml",
    "production-seed.yml",
    "sync-bellissimo-media.yml",
    "sync-canecorso-drive-images.yml",
)
for name in removed:
    assert not (ROOT / ".github/workflows" / name).exists(), (
        "A retired/noncanonical service workflow was reintroduced", name
    )
audit_workflow = (ROOT / ".github/workflows/release-audit.yml").read_text()
assert audit_workflow.count('      - "scripts/oracle_runner/stage_django.sh"') == 2, (
    "Oracle deployment script changes must run full release audit on PR and protected main"
)
assert audit_workflow.count('      - ".github/workflows/oracle-stage-django.yml"') == 2, (
    "Oracle release workflow changes must trigger full release audit on main"
)
stage=(ROOT / "scripts/oracle_runner/stage_django.sh").read_text()
assert "SUPABASE_DATABASE_URL" not in stage and "discover_supabase" not in stage
assert '[[ "$DB_MODE" == local ]]' in stage
assert 'readonly VPC_SERVICE="cca-cloudflared-vpc.service"' in stage
assert 'systemctl enable --now "$VPC_SERVICE"' in stage
assert 'systemctl is-active --quiet "$VPC_SERVICE"' in stage
assert 'assert payload.get("release") == sys.argv[2]' in stage
assert 'assert payload.get("database_backend") == "oracle-local"' in stage
assert 'Cloudflare public homepage HTTP 200' in stage

assert "SUPABASE_DATABASE_URL" not in (ROOT / ".github/workflows/oracle-stage-django.yml").read_text()
assert "Northflank is a retired" in (ROOT / "scripts/oracle_runner/edge_origin_mode.py").read_text()
assert not (ROOT / "config/settings/northflank.py").exists()
assert "SUPABASE_DATABASE_URL" not in (ROOT / ".github/workflows/database-recovery-drill.yml").read_text()
assert "verify_offsite_recovery.sh" in (ROOT / ".github/workflows/database-recovery-drill.yml").read_text()
print("PASS: runtime service inventory and active deployment paths match Oracle + Cloudflare + R2.")
for service in registry["services"]:
    print(f"  {service['id']}: {service['state']} ({service['role']})")
for service in registry["retired"]:
    print(f"  retired {service['id']}: {service['state']}")
