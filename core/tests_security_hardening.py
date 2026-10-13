from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


class SecurityHardeningTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_public_responses_include_csp_and_server_timing(self):
        response = self.client.get(reverse("home"))
        self.assertIn("Content-Security-Policy", response)
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("Server-Timing", response)

    def test_login_attempts_are_rate_limited(self):
        url = reverse("login")
        for _ in range(10):
            response = self.client.post(
                url,
                {"username": "rate-limit-user", "password": "wrong"},
                REMOTE_ADDR="203.0.113.7",
            )
            self.assertNotEqual(response.status_code, 429)

        blocked = self.client.post(
            url,
            {"username": "rate-limit-user", "password": "wrong"},
            REMOTE_ADDR="203.0.113.7",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "600")

    def test_admin_login_has_a_separate_tighter_limit(self):
        url = reverse("admin:login")
        for _ in range(5):
            response = self.client.post(
                url, {"username": "unknown-admin", "password": "wrong"},
                REMOTE_ADDR="203.0.113.117",
            )
            self.assertNotEqual(response.status_code, 429)
        blocked = self.client.post(
            url, {"username": "unknown-admin", "password": "wrong"},
            REMOTE_ADDR="203.0.113.117",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "600")

    def test_password_reset_attempts_are_rate_limited(self):
        url = reverse("password_reset")
        for _ in range(5):
            response = self.client.post(
                url,
                {"email": "nobody@example.com"},
                REMOTE_ADDR="203.0.113.8",
            )
            self.assertNotEqual(response.status_code, 429)

        blocked = self.client.post(
            url,
            {"email": "nobody@example.com"},
            REMOTE_ADDR="203.0.113.8",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "3600")

    def test_signup_attempts_are_rate_limited(self):
        url = reverse("accounts:signup")
        payload = {
            "username": "x",
            "email": "not-an-email",
            "password1": "x",
            "password2": "y",
        }
        for _ in range(5):
            response = self.client.post(
                url,
                payload,
                REMOTE_ADDR="203.0.113.9",
            )
            self.assertNotEqual(response.status_code, 429)

        blocked = self.client.post(
            url,
            payload,
            REMOTE_ADDR="203.0.113.9",
        )
        self.assertEqual(blocked.status_code, 429)

    def test_spoofed_forwarded_for_cannot_evade_login_limit(self):
        url = reverse("login")
        for attempt in range(10):
            response = self.client.post(
                url,
                {"username": "spoofed-client", "password": "wrong"},
                REMOTE_ADDR="203.0.113.50",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt + 1}",
            )
            self.assertNotEqual(response.status_code, 429)
        blocked = self.client.post(
            url,
            {"username": "spoofed-client", "password": "wrong"},
            REMOTE_ADDR="203.0.113.50",
            HTTP_X_FORWARDED_FOR="198.51.100.200",
        )
        self.assertEqual(blocked.status_code, 429)

    @override_settings(ORIGIN_EDGE_SECRET="separate-edge-secret")
    def test_separate_edge_secret_is_trusted(self):
        url = reverse("login")
        from core.middleware import AbuseProtectionMiddleware
        from django.test import RequestFactory
        request = RequestFactory().post(
            url, REMOTE_ADDR="127.0.0.1",
            HTTP_X_CCA_EDGE="1",
            HTTP_X_CCA_ORIGIN_SECRET="separate-edge-secret",
            HTTP_X_FORWARDED_FOR="198.51.100.25",
        )
        self.assertEqual(AbuseProtectionMiddleware._principal(request), "anon:198.51.100.25")

    def test_attested_edge_uses_forwarded_client_address(self):
        url = reverse("login")
        edge = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_CCA_EDGE": "1",
            "HTTP_X_CCA_ORIGIN_SECRET": settings.SECRET_KEY,
        }
        for _ in range(10):
            response = self.client.post(
                url,
                {"username": "edge-client", "password": "wrong"},
                HTTP_X_FORWARDED_FOR="198.51.100.20",
                **edge,
            )
            self.assertNotEqual(response.status_code, 429)
        response = self.client.post(
            url,
            {"username": "edge-client", "password": "wrong"},
            HTTP_X_FORWARDED_FOR="198.51.100.21",
            **edge,
        )
        self.assertNotEqual(response.status_code, 429)
