"""Read-only production SMTP authentication probe; never transmits an email.

Protect password recovery and verification by verifying configured Gmail SMTP
credentials from the actual deployed Django container. Never log credentials,
addresses, SMTP protocol responses or password-reset tokens.
"""


class EmailTransportError(RuntimeError):
    pass


def verify_transport(config, connection_factory):
    if not getattr(config, "ACCOUNT_EMAIL_ENABLED", False):
        raise EmailTransportError("Account email is disabled in the live Django configuration.")
    if getattr(config, "EMAIL_BACKEND", "") != "django.core.mail.backends.smtp.EmailBackend":
        raise EmailTransportError("Account email is not using the real SMTP backend.")
    required = (
        "EMAIL_HOST",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "DEFAULT_FROM_EMAIL",
    )
    if any(not getattr(config, key, "") for key in required):
        raise EmailTransportError("A required SMTP setting is missing.")
    connection = connection_factory(fail_silently=False)
    try:
        connection.open()  # Django performs STARTTLS and SMTP AUTH here.
        if connection.connection is None:
            raise EmailTransportError("SMTP connection could not be established.")
        status, _ = connection.connection.noop()
        if status != 250:
            raise EmailTransportError("SMTP NOOP command was not accepted.")
    except EmailTransportError:
        raise
    except Exception as exc:
        # Intentionally avoid leaking credentials, server response text and
        # user email addresses in CI logs.
        raise EmailTransportError("SMTP authentication/transport probe failed.") from exc
    finally:
        connection.close()


def main():
    import django

    django.setup()
    from django.conf import settings
    from django.core.mail import get_connection

    try:
        verify_transport(settings, get_connection)
    except EmailTransportError as exc:
        print(f"::error::{exc}")
        raise SystemExit(1) from None
    print("PASS: Production account SMTP TLS/authentication and NOOP verified; no email sent.")


if __name__ == "__main__":
    main()
