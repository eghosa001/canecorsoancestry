import os

from .production import *  # noqa: F403,F401

R2_GATEWAY_URL = os.getenv(
    "R2_GATEWAY_URL",
    "https://canecorsoancestry-edge.aighewieghosa111.workers.dev",
).rstrip("/")
MEDIA_EDGE_BASE_URL = os.getenv(
    "MEDIA_EDGE_BASE_URL",
    R2_GATEWAY_URL,
).rstrip("/")
MEDIA_EDGE_URL_TTL = int(os.getenv("MEDIA_EDGE_URL_TTL", "300"))

STORAGES = {
    "default": {
        "BACKEND": "core.cloudrun_storage.CloudflareR2GatewayStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
