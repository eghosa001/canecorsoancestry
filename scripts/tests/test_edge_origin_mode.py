#!/usr/bin/env python3
import unittest
from pathlib import Path
from scripts.oracle_runner.edge_origin_mode import (
    render, parse_origin_bindings, NORTHFLANK, ORACLE, VPC_SERVICE_ID,
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
    def test_retired_provider_is_not_an_allowed_production_origin(self):
        with self.assertRaises(ValueError):
            render(self.source, "northflank")
        payload = {"success": True, "result": {"bindings": [
            {"name": "ORIGIN_URL", "type": "plain_text", "text": NORTHFLANK},
        ]}}
        with self.assertRaisesRegex(RuntimeError, "retired"):
            parse_origin_bindings(payload)

    def test_authenticated_cloudflare_api_classifies_oracle(self):
        payload = {"success": True, "result": {"bindings": [
            {"name": "ORIGIN_URL", "type": "plain_text", "text": ORACLE},
            {"name": "ORIGIN_TRANSPORT", "type": "plain_text", "text": "private-vpc"},
            {"name": "ORIGIN_VPC", "type": "vpc_service", "service_id": VPC_SERVICE_ID},
        ]}}
        self.assertEqual(parse_origin_bindings(payload), "oracle")
        for unsafe in (
            {"name": "ORIGIN_VPC", "type": "vpc_service", "service_id": "wrong"},
            {"name": "ORIGIN_VPC", "type": "secret_text"},
        ):
            invalid = {"success": True, "result": {"bindings": [*payload["result"]["bindings"][:2], unsafe]}}
            with self.assertRaises(RuntimeError):
                parse_origin_bindings(invalid)

    def test_unknown_or_duplicate_mode_blocks_production_deployment(self):
        for payload in (
            {"success": False, "result": {}},
            {"success": True, "result": {"bindings": []}},
            {"success": True, "result": {"bindings": [
                {"name": "ORIGIN_URL", "type": "plain_text", "text": NORTHFLANK},
                {"name": "ORIGIN_URL", "type": "plain_text", "text": ORACLE},
            ]}},
            {"success": True, "result": {"bindings": [
                {"name": "ORIGIN_URL", "type": "plain_text", "text": ORACLE},
            ]}},
        ):
            with self.assertRaises(RuntimeError):
                parse_origin_bindings(payload)

    def test_fail_on_wrong_worker(self):
        with self.assertRaises(ValueError):
            render('name = "wrong"\nORIGIN_URL = "x"\n', "oracle")
        with self.assertRaises(ValueError):
            render(self.source, "unrecognized")
if __name__ == "__main__":
    unittest.main()
