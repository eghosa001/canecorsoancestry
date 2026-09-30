import os

from .production import *  # noqa: F403,F401

R2_BRIDGE_URL = os.getenv("R2_BRIDGE_URL", "http://r2.internal").rstrip("/")

STORAGES = {
    "default": {
        "BACKEND": "core.container_storage.CloudflareR2BridgeStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Static files are normally served by Workers Static Assets before the request
# reaches Django. WhiteNoise remains enabled as a safe fallback in-container.
