import os

from .base import *  # noqa: F403,F401

DEBUG = True

# The existing Render dashboard build command runs collectstatic with
# development settings. Opt into manifest generation only for that build;
# normal local development and Django tests keep the default static storage.
if os.getenv("RENDER_STATIC_BUILD", "0") == "1":
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
