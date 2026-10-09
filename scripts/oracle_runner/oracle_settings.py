"""Oracle ARM64 production origin with private local PostgreSQL and Cloudflare R2."""

import os
from django.core.exceptions import ImproperlyConfigured

from config.settings.production import *  # noqa: F403,F401

# Oracle uses R2 object storage directly through its authenticated Cloudflare
# gateway. Production storage must not import retired provider settings.
R2_GATEWAY_URL = os.getenv("R2_GATEWAY_URL", "https://canecorsoancestry-edge.aighewieghosa111.workers.dev").rstrip("/")
MEDIA_EDGE_BASE_URL = os.getenv("MEDIA_EDGE_BASE_URL", R2_GATEWAY_URL).rstrip("/")
MEDIA_EDGE_URL_TTL = int(os.getenv("MEDIA_EDGE_URL_TTL", "300"))
R2_GATEWAY_SIGNING_KEY = os.getenv("R2_GATEWAY_SIGNING_KEY", "").strip()
if not R2_GATEWAY_URL or not R2_GATEWAY_SIGNING_KEY:
    raise ImproperlyConfigured("Oracle production requires the authenticated R2 media gateway.")
STORAGES = {
    "default": {"BACKEND": "core.r2_gateway_storage.CloudflareR2GatewayStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}


# Applied before Django SecurityMiddleware, including for forged forwarded hosts.
MIDDLEWARE = [  # noqa: F405
    "scripts.oracle_runner.oracle_middleware.OracleEdgeOnlyMiddleware",
    "scripts.oracle_runner.oracle_middleware.OracleMigrationMaintenanceMiddleware",
    *MIDDLEWARE,  # noqa: F405
]
