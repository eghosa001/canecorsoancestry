from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from scripts.oracle_runner.oracle_middleware import OracleEdgeOnlyMiddleware


@override_settings(SECRET_KEY="oracle-test-secret")
class OracleOriginGuardTests(SimpleTestCase):
    def setUp(self):
        self.middleware = OracleEdgeOnlyMiddleware(lambda request: HttpResponse("ready"))
        self.factory = RequestFactory()

    def test_rejects_direct_access_even_with_forged_forwarded_host(self):
        request = self.factory.get(
            "/accounts/login/",
            HTTP_X_FORWARDED_HOST="canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_accepts_authenticated_edge(self):
        request = self.factory.get(
            "/accounts/login/",
            HTTP_X_CCA_EDGE="1",
            HTTP_X_CCA_ORIGIN_SECRET="oracle-test-secret",
        )
        self.assertEqual(self.middleware(request).status_code, 200)

    def test_health_probe_is_read_only_and_public(self):
        self.assertEqual(self.middleware(self.factory.get("/healthz/")).status_code, 200)
        self.assertEqual(self.middleware(self.factory.post("/healthz/")).status_code, 403)
