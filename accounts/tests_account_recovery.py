from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import urlparse


class AccountRecoveryTests(TestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ACCOUNT_EMAIL_ENABLED=True,
        SITE_URL="https://example.test",
    )
    def test_password_reset_sends_non_enumerating_email(self):
        get_user_model().objects.create_user(
            username="recoverable",
            email="recoverable@example.com",
            password="test-pass-123",
        )

        response = self.client.post(
            reverse("password_reset"),
            {"email": "recoverable@example.com"},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password reset", mail.outbox[0].subject.lower())
        self.assertNotIn("test-pass-123", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
        ACCOUNT_EMAIL_ENABLED=False,
    )
    def test_password_reset_does_not_claim_delivery_when_email_is_disabled(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "member@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password-reset email is temporarily unavailable")
        self.assertNotContains(response, "Check your email")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ACCOUNT_EMAIL_ENABLED=True,
    )
    def test_unknown_email_uses_same_reset_response(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "unknown@example.com"},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(mail.outbox, [])


class EmailVerificationTests(TestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ACCOUNT_EMAIL_ENABLED=True,
        REQUIRE_EMAIL_VERIFICATION=True,
        DEFAULT_FROM_EMAIL="noreply@example.com",
    )
    def test_signup_requires_email_verification_then_activates_account(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "kennel_name": "Verify Member",
                "email": "verify@example.com",
                "password1": "Strong-pass-12345",
                "password2": "Strong-pass-12345",
            },
        )

        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username="verify-member")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

        verification_url = next(
            line.strip()
            for line in mail.outbox[0].body.splitlines()
            if "/member/verify-email/" in line
        )
        activation = self.client.get(urlparse(verification_url).path)

        self.assertRedirects(activation, reverse("dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(str(self.client.session.get("_auth_user_id")), str(user.pk))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ACCOUNT_EMAIL_ENABLED=True,
        REQUIRE_EMAIL_VERIFICATION=True,
        DEFAULT_FROM_EMAIL="noreply@example.com",
    )
    def test_resend_response_does_not_disclose_account_existence(self):
        response = self.client.post(
            reverse("accounts:resend-verification"),
            {"email": "nobody@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "If an inactive account exists")
        self.assertEqual(mail.outbox, [])
