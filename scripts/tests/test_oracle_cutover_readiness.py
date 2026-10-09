"""Focused regression for Oracle health/login readiness and safe candidate update."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch, call
from scripts.oracle_runner import production_cutover as c


class OracleCutoverReadinessTests(unittest.TestCase):
    def test_http_202_waits_for_ready_true(self):
        responses = [
            json.dumps({"ready": False}).encode(),
            json.dumps({"ready": False}).encode(),
            json.dumps({"ready": True}).encode(),
        ]
        with patch.object(c, "open_checked", side_effect=responses) as fetch, \
             patch.object(c.time, "sleep") as sleep:
            c.require_auth_ready("https://candidate.test/__edge/auth-ready",
                                 {"X-CCA-Candidate-Test": "dummy"}, attempts=3)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        for x in fetch.call_args_list:
            self.assertEqual(x.kwargs["expected"], (200, 202))

    def test_fails_closed_when_oracle_login_never_ready(self):
        body = json.dumps({"ready": False}).encode()
        with patch.object(c, "open_checked", return_value=body), \
             patch.object(c.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "stayed pending"):
                c.require_auth_ready("https://candidate.test/__edge/auth-ready",
                                     attempts=2, pause_seconds=0)

    def test_http_only_northflank_rollback_refused_for_local_db(self):
        import os
        with patch.object(c, "live_mode", return_value="oracle"), \
             patch.object(c, "open_checked", return_value=b'{"database_backend":"oracle-local"}'), \
             patch.object(c, "deploy") as deploy, \
             patch.dict(os.environ, {"DJANGO_SECRET_KEY": "test-secret", "CLOUDFLARE_API_TOKEN": "test-token"}), \
             patch("sys.argv", ["cutover.py", "--mode", "northflank", "--cache-version", "test"]):
            with self.assertRaisesRegex(RuntimeError, "Refusing Northflank"):
                c.main()
            deploy.assert_not_called()

    def test_candidate_redeployment_does_not_target_live_worker(self):
        deployed = []
        class FakeRunner:
            def __call__(self, args, **kwargs):
                self.assert_candidate(args, kwargs, deployed)
        fake = FakeRunner()
        def capture(args, **kwargs):
            self.assertEqual(args[0:3], ["npx", "--yes", "wrangler@4"])
            self.assertIn("wrangler.oracle-candidate.toml", args)
            self.assertNotIn("wrangler.site.toml", args)
            config = Path("wrangler.oracle-candidate.toml").read_text(encoding="utf-8")
            self.assertIn(c.VPC_SERVICE_ID, config)
            self.assertIn('name = "canecorsoancestry-oracle-candidate"', config)
            deployed.append(True)
        config_file = Path("wrangler.oracle-candidate.toml")
        before = config_file.read_text(encoding="utf-8")
        with patch.object(c.subprocess, "run", side_effect=capture):
            c.refresh_candidate("dummy-not-a-real-secret")
        self.assertEqual(deployed, [True])
        self.assertEqual(config_file.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
