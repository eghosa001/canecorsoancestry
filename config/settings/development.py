from .base import *  # noqa: F403,F401

DEBUG = True

# Render's existing dashboard build command currently runs collectstatic with
# development settings. Keep its output compatible with the hardened Render
# runtime until the dashboard command is aligned with render.yaml.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
