import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401

DEBUG = False

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in the Worker request context.")

SITE_URL = os.getenv(
    "SITE_URL",
    "https://canecorsoancestry.com",
).rstrip("/")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "canecorsoancestry.com,www.canecorsoancestry.com,.workers.dev",
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "https://canecorsoancestry.com,https://www.canecorsoancestry.com,https://*.workers.dev",
    ).split(",")
    if origin.strip()
]

connection_string = os.getenv("CLOUDFLARE_DATABASE_URL", "").strip()
if not connection_string:
    raise ImproperlyConfigured(
        "CLOUDFLARE_DATABASE_URL must be injected from the HYPERDRIVE binding "
        "inside the Worker fetch handler."
    )

DATABASES = {
    "default": dj_database_url.parse(
        connection_string,
        conn_max_age=0,
    )
}
DATABASES["default"]["CONN_HEALTH_CHECKS"] = False
DATABASES["default"].setdefault("OPTIONS", {})["options"] = (
    "-c search_path=django_app,extensions,public"
)

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
MEDIA_URL = "/media/"
MEDIA_MIGRATION_ENABLED = os.getenv("MEDIA_MIGRATION_ENABLED", "0") == "1"

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
