"""Safety contract for the isolated backup-restore drill.

The CI suite cannot access production R2 or Oracle. These tests deliberately
verify the automation's isolation invariants without creating a fake PASS
for an actual disaster-recovery restore.
"""
import subprocess
from pathlib import Path
from unittest import TestCase

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "scripts/oracle_runner/verify_offsite_recovery.sh"
WORKFLOW = BASE / ".github/workflows/database-recovery-drill.yml"


class RecoveryDrillContractTests(TestCase):
    def test_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_drill_isolation_and_cleanup_are_preserved(self):
        script = SCRIPT.read_text()
        self.assertIn('readonly RESTORE_CONTAINER="cca-restore-$GITHUB_RUN_ID"', script)
        self.assertIn('sudo -n podman run -d --name "$RESTORE_CONTAINER" --network none', script)
        self.assertIn('trap cleanup EXIT', script)
        self.assertIn('podman rm -f "$RESTORE_CONTAINER"', script)
        self.assertIn('sha256sum "$SEALED"', script)
        self.assertIn('seal_postgres_backup.py open', script)
        self.assertIn('pg_restore', script)
        self.assertIn("docker.io/library/postgres:17", script)
        self.assertNotIn("--network container:cca-pg-shadow", script)
        self.assertNotIn("psql -h cca-pg-shadow", script)

    def test_restored_relationship_and_schema_verification_are_required(self):
        script = SCRIPT.read_text()
        self.assertIn("LEFT JOIN django_app.registry_dog sire", script)
        self.assertIn("LEFT JOIN django_app.registry_dog dam", script)
        self.assertIn("NOT i.indisvalid OR NOT i.indisready", script)
        self.assertIn("c.contype = 'f' AND NOT c.convalidated", script)
        self.assertIn('if [[ "$integrity_check" != PASS ]]', script)

    def test_weekly_schedule_and_main_only_guard(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('cron: "27 4 * * 0"', workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("runs-on: [self-hosted, linux, arm64, cca-oracle]", workflow)
        self.assertIn("scripts.tests.test_recovery_drill_contract", workflow)
