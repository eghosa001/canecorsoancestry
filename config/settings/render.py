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

if not R2_GATEWAY_URL:
    raise ImproperlyConfigured("R2_GATEWAY_URL is required on Render.")

# The public production domain is served through Cloudflare. /healthz/ stays
# directly reachable so Render can perform health checks while the rest of the
# origin can be HMAC-gated with REQUIRE_CLOUDFLARE_EDGE=1.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.CloudflareEdgeMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]

# Render's free filesystem is ephemeral. Keep all user-uploaded media in R2
# through the signed Cloudflare Worker gateway, while WhiteNoise remains a
# fallback for static assets if they are requested from the origin directly.
STORAGES = {
    "default": {
        "BACKEND": "core.r2_gateway_storage.CloudflareR2GatewayStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
