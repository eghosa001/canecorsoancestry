import hashlib
import hmac
import os
from unittest.mock import patch

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from core.middleware import CloudRunEdgeMiddleware


class CloudRunEdgeMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"})
    def test_direct_application_request_is_blocked(self):
        middleware = CloudRunEdgeMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(self.factory.get("/dogs/"))
        self.assertEqual(response.status_code, 403)

    @patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"})
    def test_valid_cloudflare_edge_signature_is_allowed(self):
        signature = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            b"canecorsoancestry-cloud-run-edge",
            hashlib.sha256,
        ).hexdigest()
        middleware = CloudRunEdgeMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(
            self.factory.get(
                "/dogs/",
                HTTP_X_CANE_EDGE_AUTH=signature,
            )
        )
        self.assertEqual(response.status_code, 200)

    @patch.dict(os.environ, {"REQUIRE_CLOUDFLARE_EDGE": "1"})
    def test_health_endpoint_remains_available_for_cloud_run_checks(self):
        middleware = CloudRunEdgeMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(self.factory.get("/healthz/"))
        self.assertEqual(response.status_code, 200)
