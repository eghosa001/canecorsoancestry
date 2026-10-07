import os

from django.core.exceptions import ImproperlyConfigured

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
R2_GATEWAY_SIGNING_KEY = os.getenv("R2_GATEWAY_SIGNING_KEY", "").strip()

if not R2_GATEWAY_URL:
    raise ImproperlyConfigured(
        "R2_GATEWAY_URL is required for the hosted production service."
    )
if not R2_GATEWAY_SIGNING_KEY:
    raise ImproperlyConfigured(
        "R2_GATEWAY_SIGNING_KEY is required for hosted media storage."
    )

# Northflank runs the Django origin while Cloudflare remains the public edge
# and R2 remains the media store. Keeping media behind the existing gateway
# means changing the application host does not require moving dog images.
# Use compressed non-manifest static storage on Northflank. The container
# already runs collectstatic at build time, and avoiding a manifest lookup
# prevents runtime 500s if Northflank rolls between immutable images.
STORAGES = {
    "default": {
        "BACKEND": "core.r2_gateway_storage.CloudflareR2GatewayStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
