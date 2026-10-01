from django.test import RequestFactory, SimpleTestCase, override_settings
from django.http import HttpResponse

from core.middleware import RequestSecurityMiddleware


@override_settings(
    SITE_URL="https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
)
class CanonicalPublicSiteTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestSecurityMiddleware(lambda request: HttpResponse("ok"))

    def test_direct_render_get_redirects_to_cloudflare(self):
        request = self.factory.get(
            "/dogs/example/?q=abc",
            HTTP_HOST="canecorsoancestry.onrender.com",
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response["Location"],
            "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev/dogs/example/?q=abc",
        )

    def test_cloudflare_origin_request_is_not_redirected(self):
        request = self.factory.get(
            "/dogs/example/",
            HTTP_HOST="canecorsoancestry.onrender.com",
            HTTP_X_CCA_EDGE="1",
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_render_health_check_is_not_redirected(self):
        request = self.factory.get(
            "/healthz/",
            HTTP_HOST="canecorsoancestry.onrender.com",
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
