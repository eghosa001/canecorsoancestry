from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


class PasswordResetReadinessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="email-recovery-member",
            email="member@example.com",
            password="test-pass-123",
        )

    @override_settings(
        ACCOUNT_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@canecorsoancestry.example",
    )
    def test_password_reset_sends_recovery_email_when_email_is_enabled(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(
            response,
            reverse("password_reset_done"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("password", mail.outbox[0].subject.lower())

    @override_settings(
        ACCOUNT_EMAIL_ENABLED=False,
        EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
    )
    def test_password_reset_does_not_claim_success_when_email_is_unavailable(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password-reset email is temporarily unavailable.")
