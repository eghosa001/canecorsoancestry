"""Build-time settings: generate production-compressed static assets without secrets.

Runtime uses config.settings.northflank, whose WhiteNoise backend serves
these precompressed assets. This module must never be used to serve traffic.
"""
from .development import *  # noqa: F403,F401

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
