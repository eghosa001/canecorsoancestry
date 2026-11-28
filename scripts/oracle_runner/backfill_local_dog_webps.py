"""Bounded local photo WebP backfill. Runs inside the protected Oracle container."""
import os
import shutil
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.oracle_runner.oracle_settings")
import django
django.setup()

from django.conf import settings
from django.core.files.storage import default_storage
from core.local_photo_renditions import WIDTHS, build_previews, existing_preview
from registry.models import DogImage

if getattr(settings, "CCA_MEDIA_BACKEND", "") != "oracle-local":
    raise SystemExit("Refusing local conversion outside Oracle-local media mode")
root = Path(settings.MEDIA_ROOT)
if not root.is_dir():
    raise SystemExit("Persistent media root unavailable")
cache = root / "cca-photo-renditions" / "local-v1"
size = sum(p.stat().st_size for p in cache.rglob("*.webp") if p.is_file()) if cache.exists() else 0
cap = 768 * 1024**2
optimized = ready = missing = failed = 0
keys = DogImage.objects.filter(image__startswith="dogs/").order_by("-created_at").values_list("image", flat=True).iterator(chunk_size=250)
for key in keys:
    if optimized >= 45 or size >= cap or shutil.disk_usage(root).free < 4 * 1024**3:
        break
    if not default_storage.exists(key):
        missing += 1
        continue
    if all(existing_preview(key, variant) for variant in WIDTHS):
        ready += 1
        continue
    try:
        if build_previews(key):
            optimized += 1
            size += sum(p.stat().st_size for variant in WIDTHS if (p := existing_preview(key, variant)))
    except (OSError, ValueError) as exc:
        failed += 1
        if failed <= 3:
            print("LOCAL_PREVIEW_ERROR", type(exc).__name__, flush=True)
        if failed >= 10:
            break
print(f"LOCAL_WEBP optimized={optimized} ready={ready} missing_originals={missing} conversion_errors={failed} approximate_cache_bytes={size}", flush=True)
if failed:
    raise SystemExit("Local WebP conversion failed for some existing originals")
