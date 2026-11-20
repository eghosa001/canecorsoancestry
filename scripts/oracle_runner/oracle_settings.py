"""Oracle ARM64 production origin with private local PostgreSQL and Cloudflare R2."""

import os
from django.core.exceptions import ImproperlyConfigured

from config.settings.production import *  # noqa: F403,F401

# Billing support contact approved for the public production site. Allow the
# repository variable to override it; an unset/blank value uses this address.
SUPPORT_EMAIL = os.getenv("CCA_SUPPORT_EMAIL", "").strip() or "canecorsoancestry@gmail.com"

# Cloudflare Worker should never retain the root Django SECRET_KEY. This
# credential is domain-separated by HMAC during deployment.
ORIGIN_EDGE_SECRET = os.getenv("CCA_ORIGIN_EDGE_SECRET", "").strip()
if not ORIGIN_EDGE_SECRET or ORIGIN_EDGE_SECRET == SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("Oracle production requires a distinct Cloudflare origin credential.")

# Oracle-local media is an opt-in no-subscription alternative. All private
# media still passes through Django's per-file authorization at /media/.
# Mount /var/lib/cca/media into /app/media before enabling this backend.
CCA_MEDIA_BACKEND = os.getenv("CCA_MEDIA_BACKEND", "r2").strip().lower()
if CCA_MEDIA_BACKEND not in {"r2", "oracle-local"}:
    raise ImproperlyConfigured("CCA_MEDIA_BACKEND must be r2 or oracle-local.")

R2_GATEWAY_URL = os.getenv("R2_GATEWAY_URL", "https://media.canecorsoancestry.com").rstrip("/")
MEDIA_EDGE_URL_TTL = int(os.getenv("MEDIA_EDGE_URL_TTL", "300"))
R2_GATEWAY_SIGNING_KEY = os.getenv("R2_GATEWAY_SIGNING_KEY", "").strip()

if CCA_MEDIA_BACKEND == "r2":
    MEDIA_EDGE_BASE_URL = os.getenv("MEDIA_EDGE_BASE_URL", R2_GATEWAY_URL).rstrip("/")
    if not R2_GATEWAY_URL or not R2_GATEWAY_SIGNING_KEY:
        raise ImproperlyConfigured("Oracle production requires the authenticated R2 media gateway.")
    media_storage = "core.r2_gateway_storage.CloudflareR2GatewayStorage"
else:
    # Stop generating signed R2 URLs. Existing templates fall back to the
    # permission-checked /media/ route, and files stay on the persistent VM disk.
    MEDIA_EDGE_BASE_URL = ""
    MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405
    media_storage = "django.core.files.storage.FileSystemStorage"

STORAGES = {
    "default": {"BACKEND": media_storage},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}


# Applied before Django SecurityMiddleware, including for forged forwarded hosts.
MIDDLEWARE = [  # noqa: F405
    "scripts.oracle_runner.oracle_middleware.OracleEdgeOnlyMiddleware",
    "scripts.oracle_runner.oracle_middleware.OracleMigrationMaintenanceMiddleware",
    *MIDDLEWARE,  # noqa: F405
]
