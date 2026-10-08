from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


class PasswordRecoveryReadinessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="recovery-member",
            email="member@example.com",
            password="initial-pass-123",
        )

    @override_settings(
        ACCOUNT_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="noreply@canecorsoancestry.test",
    )
    def test_password_reset_sends_real_reset_link_when_email_is_enabled(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        self.assertIn("/accounts/reset/", message.body)

    @override_settings(
        ACCOUNT_EMAIL_ENABLED=False,
        EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
    )
    def test_password_reset_refuses_to_fake_success_when_email_is_disabled(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password-reset email is temporarily unavailable")
        self.assertNotContains(response, "password_reset_done")
