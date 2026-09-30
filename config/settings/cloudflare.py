from django.core.exceptions import ImproperlyConfigured
from workers import env

from .base import *  # noqa: F403,F401

DEBUG = False


def _binding_text(name, default=""):
    value = getattr(env, name, default)
    return str(value or default)


SECRET_KEY = _binding_text("DJANGO_SECRET_KEY").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY Worker secret is required.")

SITE_URL = _binding_text(
    "SITE_URL",
    "https://canecorsoancestry.com",
).rstrip("/")

ALLOWED_HOSTS = [
    host.strip()
    for host in _binding_text(
        "DJANGO_ALLOWED_HOSTS",
        "canecorsoancestry.com,www.canecorsoancestry.com,.workers.dev",
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in _binding_text(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "https://canecorsoancestry.com,https://www.canecorsoancestry.com,https://*.workers.dev",
    ).split(",")
    if origin.strip()
]

# Django's app registry is initialized during Worker startup. Use the dummy
# backend there so Cloudflare does not import psycopg or touch Hyperdrive while
# validating global scope. worker.py replaces this entry before request 1.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.dummy",
        "NAME": "cloudflare-startup-placeholder",
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
MEDIA_URL = "/media/"
MEDIA_MIGRATION_ENABLED = _binding_text("MEDIA_MIGRATION_ENABLED", "0") == "1"

STORAGES = {
    "default": {
        "BACKEND": "core.storage.CloudflareR2Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

ANCESTRY_EMAIL_NOTIFICATIONS = False
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
SENTRY_DSN = ""
