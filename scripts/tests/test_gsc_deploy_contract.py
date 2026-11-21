"""Guard Search Console credential forwarding across both Oracle deploy routes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SearchConsoleDeployContractTests(unittest.TestCase):
    def test_oracle_deploy_workflows_forward_encrypted_gsc_secret(self):
        for relative in (
            ".github/workflows/release-audit.yml",
            ".github/workflows/oracle-stage-django.yml",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                "CCA_GSC_SERVICE_ACCOUNT_JSON: " +
                "${{ secrets.CCA_GSC_SERVICE_ACCOUNT_JSON }}",
                source,
                msg=relative,
            )

    def test_production_env_uses_single_line_encoded_credential(self):
        script = (ROOT / "scripts/oracle_runner/stage_django.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'gsc_secret = os.environ.get("CCA_GSC_SERVICE_ACCOUNT_JSON", "")',
            script,
        )
        self.assertIn(
            'values["CCA_GSC_SERVICE_ACCOUNT_B64"] = base64.b64encode(',
            script,
        )
        self.assertIn(
            'sudo -n install -o root -g root -m 600 "$temporary_env" "$APP_ENV"',
            script,
        )
        self.assertNotIn('echo "$gsc_secret"', script)


if __name__ == "__main__":
    unittest.main()
