"""Disposable, non-production settings for CI's browser audit only."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .development import *  # noqa: F401,F403

if os.environ.get("CCA_QA_ISOLATED") != "1":
    raise ImproperlyConfigured("QA audit requires explicit CCA_QA_ISOLATED=1")

database_url = os.environ.get("DATABASE_URL", "")
if not database_url.startswith("sqlite:////"):
    raise ImproperlyConfigured("QA audit requires a disposable absolute-path SQLite DATABASE_URL")
if any(token in database_url.lower() for token in ("prod", "live", "supabase")):
    raise ImproperlyConfigured("Refusing a potentially production-named QA database")

MEDIA_ROOT = Path(os.environ["CCA_QA_MEDIA_ROOT"])
EMAIL_FILE_PATH = Path(os.environ["CCA_QA_MAIL_ROOT"])
if not MEDIA_ROOT.is_absolute() or not EMAIL_FILE_PATH.is_absolute():
    raise ImproperlyConfigured("QA media and mail directories must be absolute")
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
EMAIL_FILE_PATH.mkdir(parents=True, exist_ok=True)
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
ACCOUNT_EMAIL_ENABLED = True
REQUIRE_EMAIL_VERIFICATION = True
EMAIL_HOST = ""
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
PAYSTACK_SECRET_KEY = ""
SITE_URL = "http://127.0.0.1:8000"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000"]

# Synthetic browser suites sign into 13+ isolated accounts per browser.
# Preserve every production limiter; extend only the local QA login budget.
MIDDLEWARE = [
    "scripts.qa_rate_limit.IsolatedQAAbuseProtectionMiddleware"
    if name == "core.middleware.AbuseProtectionMiddleware" else name
    for name in MIDDLEWARE
]
