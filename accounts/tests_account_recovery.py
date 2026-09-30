from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


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
