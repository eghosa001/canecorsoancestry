import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401

DEBUG = False

if not os.getenv("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production.")
if not os.getenv("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL is required in production.")
if not os.getenv("DJANGO_ALLOWED_HOSTS"):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production.")
if not os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS"):
    raise ImproperlyConfigured("DJANGO_CSRF_TRUSTED_ORIGINS is required in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"
SECURE_HSTS_PRELOAD = os.getenv("DJANGO_HSTS_PRELOAD", "0") == "1"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Render overrides the default storage backend with the R2 media gateway.
# Keeping production.py storage-neutral avoids stale provider-specific branches.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

if ANCESTRY_EMAIL_NOTIFICATIONS:  # noqa: F405
    missing_email = [
        name
        for name, value in {
            "EMAIL_HOST": EMAIL_HOST,  # noqa: F405
            "EMAIL_HOST_USER": EMAIL_HOST_USER,  # noqa: F405
            "EMAIL_HOST_PASSWORD": EMAIL_HOST_PASSWORD,  # noqa: F405
        }.items()
        if not value
    ]
    if missing_email:
        raise ImproperlyConfigured(
            "Email notifications are enabled but these settings are missing: "
            + ", ".join(missing_email)
        )
