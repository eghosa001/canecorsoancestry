from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path

from config.urls import urlpatterns as project_urlpatterns


def boom(_request):
    raise RuntimeError("intentional production error-page test")


urlpatterns = [
    *project_urlpatterns,
    path("boom/", boom),
]


@override_settings(DEBUG=False)
class BrandedErrorPageTests(TestCase):
    def test_404_uses_branded_recovery_page(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "404 · Page not found", status_code=404)
        self.assertContains(response, "Search dogs", status_code=404)

    @override_settings(ROOT_URLCONF="core.tests_production_readiness")
    def test_500_uses_branded_recovery_page(self):
        self.client.raise_request_exception = False
        response = self.client.get("/boom/")
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Temporary service issue", status_code=500)
        self.assertContains(response, "Return home", status_code=500)


class PublicPolicyPagesTests(TestCase):
    def test_public_policies_use_live_prices_and_footer_navigation(self):
        response = self.client.get("/billing-policy/")
        self.assertContains(response, "₦1,500")
        self.assertNotContains(response, "₦1,000")
        self.assertContains(response, "review, not guaranteed publication")
        for path in ("/privacy/", "/terms/"):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertContains(self.client.get("/"), 'href="/privacy/"')
        self.assertContains(self.client.get("/"), 'href="/terms/"')
