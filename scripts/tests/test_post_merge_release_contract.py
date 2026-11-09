"""Prevent post-merge release dispatch from bypassing protected Oracle gates."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PostMergeReleaseContractTests(unittest.TestCase):
    def test_dispatch_only_on_merged_main_application_pull_requests(self):
        policy = (ROOT / ".github/workflows/post-merge-release.yml").read_text()
        self.assertIn("types: [closed]", policy)
        self.assertIn("branches: [main]", policy)
        self.assertIn("github.event.pull_request.merged == true", policy)
        self.assertIn("github.event.pull_request.base.ref == 'main'", policy)
        self.assertIn("gh workflow run release-audit.yml", policy)
        self.assertIn("--ref main", policy)
        self.assertNotIn("gh workflow run oracle-stage-django.yml", policy)

    def test_oracle_deploy_is_a_direct_child_of_full_audit_gates(self):
        audit = (ROOT / ".github/workflows/release-audit.yml").read_text()
        self.assertIn("oracle-production:", audit)
        self.assertIn("needs: [django-sqlite, django-postgres, security-and-edge]", audit)
        self.assertIn("github.ref == 'refs/heads/main'", audit)
        self.assertIn("github.event_name == 'workflow_dispatch'", audit)
        self.assertIn("github.event_name == 'push'", audit)
        self.assertIn("runs-on: [self-hosted, linux, arm64, cca-oracle]", audit)
        self.assertIn("Audited commit is no longer current main", audit)
        self.assertIn("check_offsite_backup_freshness.sh", audit)
        self.assertIn("stage_django.sh", audit)

    def test_standalone_oracle_workflow_is_manual_fallback_only(self):
        oracle = (ROOT / ".github/workflows/oracle-stage-django.yml").read_text()
        self.assertIn("github.event_name == 'workflow_dispatch'", oracle)
        self.assertIn("github.ref == 'refs/heads/main'", oracle)
        self.assertNotIn("workflow_run:", oracle)
        self.assertIn("Only update the current protected main commit", oracle)
        self.assertIn("check_offsite_backup_freshness.sh", oracle)
        self.assertIn("stage_django.sh", oracle)
        audit = (ROOT / ".github/workflows/release-audit.yml").read_text()
        self.assertIn("needs: [django-sqlite, django-postgres, security-and-edge]", audit)
        self.assertIn("name: Deploy audited main to Oracle", audit)
        self.assertIn("github.ref == 'refs/heads/main'", audit)
        self.assertIn("check_offsite_backup_freshness.sh", audit)
        self.assertIn("stage_django.sh", audit)

    def test_pdf_deployment_is_required_by_live_release_gate(self):
        script = (ROOT / "scripts/oracle_runner/stage_django.sh").read_text()
        self.assertIn("pdf-release-probe/export.pdf", script)
        self.assertIn("member_pdf_status", script)
        self.assertIn('"$pdf_status" != 302', script)
        self.assertIn('"$member_pdf_status" != 302', script)
        self.assertIn('"$CCA_RELEASE_SHA"', script)


if __name__ == "__main__":
    unittest.main()
