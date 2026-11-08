"""Check SMTP authentication without ever sending a password-reset email."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from scripts.check_account_email_transport import EmailTransportError, verify_transport


def config(**overrides):
    values = dict(
        ACCOUNT_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        EMAIL_HOST_USER="sender@example.test",
        EMAIL_HOST_PASSWORD="test-only-placeholder",
        DEFAULT_FROM_EMAIL="sender@example.test",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class AccountEmailTransportTests(TestCase):
    def test_authentication_probe_never_sends_email(self):
        backend = MagicMock()
        backend.connection.noop.return_value = (250, b"ok")
        factory = MagicMock(return_value=backend)
        verify_transport(config(), factory)
        factory.assert_called_once_with(fail_silently=False)
        backend.open.assert_called_once_with()
        backend.connection.noop.assert_called_once_with()
        backend.send_messages.assert_not_called()
        backend.close.assert_called_once_with()

    def test_disabled_or_dummy_account_email_fails(self):
        for bad in (
            {"ACCOUNT_EMAIL_ENABLED": False},
            {"EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend"},
            {"EMAIL_HOST_PASSWORD": ""},
        ):
            with self.subTest(bad=bad), self.assertRaises(EmailTransportError):
                verify_transport(config(**bad), MagicMock())

    def test_rejected_smtp_auth_fails_without_exposing_exception_details(self):
        backend = MagicMock()
        backend.open.side_effect = RuntimeError("server leaked credential payload")
        with self.assertRaises(EmailTransportError) as ctx:
            verify_transport(config(), MagicMock(return_value=backend))
        self.assertNotIn("credential payload", str(ctx.exception))
        backend.close.assert_called_once_with()

    def test_failed_noop_also_closes_connection(self):
        backend = MagicMock()
        backend.connection.noop.return_value = (421, b"Unavailable")
        with self.assertRaises(EmailTransportError):
            verify_transport(config(), MagicMock(return_value=backend))
        backend.send_messages.assert_not_called()
        backend.close.assert_called_once_with()
