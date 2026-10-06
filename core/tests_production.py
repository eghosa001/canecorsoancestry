from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from registry.models import Dog, Kennel


class ProductionSurfaceTests(TestCase):
    def test_health_check_probes_database(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^healthz/$"])
    def test_health_check_is_not_redirected_by_https_enforcement(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)

    def test_security_and_request_trace_headers_are_present(self):
        response = self.client.get(reverse("home"))
        self.assertIn("X-Request-ID", response)
        self.assertEqual(response["X-Permitted-Cross-Domain-Policies"], "none")
        self.assertIn("geolocation=()", response["Permissions-Policy"])

    def test_robots_blocks_private_surfaces_and_links_sitemap(self):
        body = self.client.get(reverse("robots")).content.decode()
        self.assertIn("Disallow: /member/", body)
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("/sitemap.xml", body)

    def test_sitemap_excludes_private_dogs(self):
        Dog.objects.create(name="Public Dog", slug="public-dog", is_public=True)
        Dog.objects.create(name="Private Dog", slug="private-dog", is_public=False)
        index_body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("sitemap-dogs.xml", index_body)
        body = self.client.get(
            reverse("sitemap-section", kwargs={"section": "dogs"})
        ).content.decode()
        self.assertIn("public-dog", body)
        self.assertNotIn("private-dog", body)

    def test_public_dog_profile_has_structured_data(self):
        kennel = Kennel.objects.create(name="SEO Kennel", slug="seo-kennel")
        dog = Dog.objects.create(name="Structured Dog", slug="structured-dog", kennel=kennel, is_public=True)
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(response, 'type="application/ld+json"')
        self.assertContains(response, "Structured Dog")

    def test_private_member_surfaces_are_noindex_and_not_cached(self):
        user = get_user_model().objects.create_user(username="member", password="test-pass-123")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertIn("no-store", response["Cache-Control"])

    @override_settings(SITE_URL="https://canecorsoancestry.example")
    def test_direct_origin_rejects_spoofed_edge_marker(self):
        response = self.client.get(
            reverse("home"),
            HTTP_HOST="origin.code.run",
            HTTP_X_CCA_EDGE="1",
        )
        self.assertEqual(response.status_code, 308)
        self.assertTrue(response["Location"].startswith("https://canecorsoancestry.example/"))

    @override_settings(SITE_URL="https://canecorsoancestry.example")
    def test_direct_origin_accepts_authenticated_edge_request(self):
        from django.conf import settings

        response = self.client.get(
            reverse("home"),
            HTTP_HOST="origin.code.run",
            HTTP_X_CCA_EDGE="1",
            HTTP_X_CCA_ORIGIN_SECRET=settings.SECRET_KEY,
        )
        self.assertEqual(response.status_code, 200)

    def test_moderation_requires_staff(self):
        user = get_user_model().objects.create_user(username="ordinary", password="test-pass-123")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:moderation"))
        self.assertEqual(response.status_code, 403)
