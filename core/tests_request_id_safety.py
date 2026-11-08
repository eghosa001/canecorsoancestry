"""Untrusted correlation ID is never reflected into security headers or logs."""
import re

from django.test import TestCase

from core.middleware import safe_request_id


class RequestIdSafetyTests(TestCase):
    def test_preserves_valid_upstream_trace_id(self):
        value = "cf-ray-6cdE4:edge.1"
        self.assertEqual(safe_request_id(value), value)
        response = self.client.get("/healthz/", HTTP_X_REQUEST_ID=value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], value)

    def test_invalid_trace_ids_replaced_not_reflected(self):
        for raw in (
            "line-one\nline-two",
            "line-one\rline-two",
            "spoof\x00null",
            " spaced-id",
            "../bad",
            "💥" * 10,
            "x" * 1024,
            "",
        ):
            with self.subTest(value=repr(raw)):
                result = safe_request_id(raw)
                self.assertRegex(result, r"^[0-9a-f]{32}$")
                self.assertNotEqual(result, raw)

    def test_long_and_control_character_header_causes_no_500(self):
        response = self.client.get("/healthz/", HTTP_X_REQUEST_ID="z" * 500)
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")
        self.assertNotIn("z" * 500, response["X-Request-ID"])
