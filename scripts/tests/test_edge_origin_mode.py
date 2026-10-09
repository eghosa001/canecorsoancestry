#!/usr/bin/env python3
import unittest
from pathlib import Path
from scripts.oracle_runner.edge_origin_mode import (
    render, NORTHFLANK, ORACLE, VPC_SERVICE_ID,
)

class OriginModeTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("wrangler.site.toml").read_text(encoding="utf-8")
    def test_oracle_has_only_private_binding(self):
        updated = render(self.source, "oracle")
        self.assertIn(f'ORIGIN_URL = "{ORACLE}"', updated)
        self.assertIn('ORIGIN_TRANSPORT = "private-vpc"', updated)
        self.assertIn(VPC_SERVICE_ID, updated)
        self.assertEqual(updated.count("[[vpc_services]]"), 1)
        self.assertEqual(render(updated, "oracle"), updated)
    def test_restore_legacy(self):
        original = render(render(self.source, "oracle"), "northflank")
        self.assertIn(f'ORIGIN_URL = "{NORTHFLANK}"', original)
        self.assertNotIn("private-vpc", original)
        self.assertNotIn("[[vpc_services]]", original)
        self.assertNotIn(VPC_SERVICE_ID, original)
        self.assertEqual(render(original, "northflank"), original)
    def test_fail_on_wrong_worker(self):
        with self.assertRaises(ValueError):
            render('name = "wrong"\nORIGIN_URL = "x"\n', "oracle")
        with self.assertRaises(ValueError):
            render(self.source, "unrecognized")
if __name__ == "__main__":
    unittest.main()
