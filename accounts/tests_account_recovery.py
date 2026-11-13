from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import urlparse


class AccountRecoveryTests(TestCase):
    def test_regular_sign_in_accepts_email_and_username(self):
        user = get_user_model().objects.create_user(
            username="signin-member", email="signin-member@example.test", password="Member-password-123",
        )
        for identity in ("signin-member@example.test", "signin-member"):
            with self.subTest(identity=identity):
                self.client.logout()
                response = self.client.post(reverse("login"), {
                    "username": identity, "password": "Member-password-123",
                })
                self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
                self.assertEqual(str(self.client.session["_auth_user_id"]), str(user.pk))

    def test_super_admin_can_sign_in_from_public_site_by_username(self):
        owner = get_user_model().objects.create_superuser(
            username="admin-without-email", email="", password="Admin-password-123",
        )
        response = self.client.post(reverse("login"), {
            "username": "admin-without-email", "password": "Admin-password-123",
        })
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(str(self.client.session["_auth_user_id"]), str(owner.pk))
        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(admin_response.status_code, 200)

    def test_sign_in_explains_staff_and_super_admin_access(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Email or username")
        self.assertContains(response, reverse("admin:login"))
        self.assertContains(response, "Moderators should use the form above.")

    @override_settings(ACCOUNT_EMAIL_ENABLED=False)
    def test_login_keeps_password_recovery_discoverable_when_email_is_disabled(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("password_reset"))
        self.assertContains(response, "Forgot your password?")
        self.assertNotContains(response, "Resend verification")

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


    @override_settings(PASSWORD_RESET_TIMEOUT=1)
    def test_expired_password_reset_token_cannot_be_reused(self):
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from django.contrib.auth.tokens import default_token_generator

        user = get_user_model().objects.create_user(
            username="expired-reset", email="expired-reset@example.test",
            password="Old-long-pass-1234",
        )
        issued = datetime(2026, 11, 1, 12, 0, 0)
        with patch.object(default_token_generator, "_now", return_value=issued):
            token = default_token_generator.make_token(user)
            self.assertTrue(default_token_generator.check_token(user, token))
        with patch.object(default_token_generator, "_now", return_value=issued + timedelta(seconds=2)):
            self.assertFalse(default_token_generator.check_token(user, token))

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
