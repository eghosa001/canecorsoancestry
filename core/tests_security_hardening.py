from django.core.cache import cache
from django.test import TestCase
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
