import hashlib
import hmac
import os
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware import CloudflareEdgeMiddleware, EDGE_AUTH_MESSAGE


@override_settings(SECRET_KEY="edge-test-secret")
class CloudflareEdgeMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def middleware(self):
        return CloudflareEdgeMiddleware(lambda request: HttpResponse("ok"))

    def test_direct_application_request_is_rejected_when_gate_enabled(self):
        with patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"}):
            response = self.middleware()(self.factory.get("/"))

        self.assertEqual(response.status_code, 403)

    def test_health_check_stays_available_to_render(self):
        with patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"}):
            response = self.middleware()(self.factory.get("/healthz/"))

        self.assertEqual(response.status_code, 200)

    def test_valid_cloudflare_signature_is_accepted(self):
        signature = hmac.new(
            b"edge-test-secret",
            EDGE_AUTH_MESSAGE,
            hashlib.sha256,
        ).hexdigest()
        request = self.factory.get(
            "/dogs/",
            headers={"X-Cane-Edge-Auth": signature},
        )

        with patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"}):
            response = self.middleware()(request)

        self.assertEqual(response.status_code, 200)
