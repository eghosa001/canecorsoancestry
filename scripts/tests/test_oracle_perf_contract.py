"""Regression: diagnostics must measure authorized public requests, not forge edge credentials."""
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/oracle_runner/oracle_perf_diagnostics.sh"
WORKFLOW = ROOT / ".github/workflows/oracle-perf-diagnostics.yml"


class OraclePerformanceContractTests(TestCase):
    def test_uses_real_edge_without_django_secret_key(self):
        script = SCRIPT.read_text()
        workflow = WORKFLOW.read_text()
        self.assertIn("https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev$path", script)
        self.assertNotIn('X-CCA-Origin-Secret:', script)
        self.assertNotIn('$DJANGO_SECRET_KEY', script)
        self.assertNotIn('secrets.DJANGO_SECRET_KEY', workflow)
        self.assertIn('browse_ttfb', script)
        self.assertIn("active_database_sql_median_ms", script)
