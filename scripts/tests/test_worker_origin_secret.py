"""Guard the site-edge roll-out contract without hitting live accounts."""
from pathlib import Path
import unittest

class EdgeCredentialIsolationTests(unittest.TestCase):
    def test_worker_uses_domain_separated_secret_and_blocks_unsafe_order(self):
        workflow = Path(".github/workflows/cloudflare-site-edge.yml").read_text()
        self.assertIn('b"cca-origin-edge-auth-v1"', workflow)
        self.assertIn("verify-derived-origin-secret", workflow)
        self.assertIn("needs: [validate, verify-derived-origin-secret]", workflow)
        self.assertNotIn('json.dumps({"ORIGIN_EDGE_SECRET": os.environ["DJANGO_SECRET_KEY"]})', workflow)
        stage = Path("scripts/oracle_runner/stage_django.sh").read_text()
        self.assertIn('b"cca-origin-edge-auth-v1"', stage)

if __name__ == "__main__":
    unittest.main()
