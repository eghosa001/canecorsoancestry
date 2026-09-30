import os
import re
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SITE_NAME = "Cane Corso Ancestry"
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "core",
    "accounts",
    "registry",
    "pedigrees",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.RequestSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AbuseProtectionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context_processors.site_metadata",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": dj_database_url.config(
    default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    conn_max_age=int(os.getenv("DJANGO_DB_CONN_MAX_AGE", "300")),
)}
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

database = DATABASES["default"]
if database.get("ENGINE", "").endswith("postgresql"):
    db_schema = os.getenv("DJANGO_DB_SCHEMA", "").strip()
    db_sslmode = os.getenv("DJANGO_DB_SSLMODE", "").strip()
    db_options = database.setdefault("OPTIONS", {})

    if db_schema:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_schema):
            raise ImproperlyConfigured(
                "DJANGO_DB_SCHEMA must be a valid PostgreSQL identifier."
            )
        extra_schemas = [
            item.strip()
            for item in os.getenv(
                "DJANGO_DB_EXTRA_SCHEMAS",
                "extensions,public",
            ).split(",")
            if item.strip()
        ]
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema)
            for schema in extra_schemas
        ):
            raise ImproperlyConfigured(
                "DJANGO_DB_EXTRA_SCHEMAS must contain valid PostgreSQL identifiers."
            )
        search_path = ",".join(dict.fromkeys([db_schema, *extra_schemas]))
        existing_options = db_options.get("options", "").strip()
        search_path_option = f"-c search_path={search_path}"
        db_options["options"] = (
            f"{existing_options} {search_path_option}".strip()
        )

    if db_sslmode:
        db_options["sslmode"] = db_sslmode

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": os.getenv("DJANGO_CACHE_LOCATION", "canecorsoancestry"),
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60
PASSWORD_RESET_TIMEOUT = 60 * 60

DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(25 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(5 * 1024 * 1024)))

ANCESTRY_EMAIL_NOTIFICATIONS = os.getenv("ANCESTRY_EMAIL_NOTIFICATIONS", "0") == "1"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Cane Corso Ancestry <noreply@canecorsoancestry.com>")
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
ACCOUNT_EMAIL_ENABLED = os.getenv(
    "ACCOUNT_EMAIL_ENABLED",
    "1" if EMAIL_HOST else "0",
) == "1"
REQUIRE_EMAIL_VERIFICATION = os.getenv(
    "REQUIRE_EMAIL_VERIFICATION",
    "1" if ACCOUNT_EMAIL_ENABLED else "0",
) == "1"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
