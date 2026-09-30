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

bucket_name = os.getenv("AWS_STORAGE_BUCKET_NAME") or os.getenv("BUCKET")
bucket_region = os.getenv("AWS_S3_REGION_NAME") or os.getenv("REGION")
bucket_endpoint = os.getenv("AWS_S3_ENDPOINT_URL") or os.getenv("ENDPOINT")
bucket_access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
bucket_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
require_object_storage = os.getenv("DJANGO_REQUIRE_OBJECT_STORAGE", "0") == "1"
bucket_ready = all(
    (
        bucket_name,
        bucket_region,
        bucket_endpoint,
        bucket_access_key,
        bucket_secret_key,
    )
)
if require_object_storage and not bucket_ready:
    raise ImproperlyConfigured(
        "Production object storage is required but S3-compatible bucket credentials are incomplete."
    )

if bucket_ready:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": bucket_name,
                "region_name": bucket_region,
                "endpoint_url": bucket_endpoint,
                "access_key": bucket_access_key,
                "secret_key": bucket_secret_key,
                "location": "media",
                "default_acl": None,
                "file_overwrite": False,
                "querystring_auth": True,
                "querystring_expire": 3600,
                "addressing_style": "path",
                "signature_version": "s3v4",
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
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

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("RENDER_GIT_COMMIT") or os.getenv("K_REVISION") or None,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
    )
