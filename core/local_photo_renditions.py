"""Bounded Oracle-local dog photo derivatives; originals remain untouched."""
import hashlib
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

WIDTHS = {"thumb": 176, "card": 480, "portrait": 960}
SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif")
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 36_000_000


def preview_paths(key, variant):
    if (variant not in WIDTHS or not key.startswith("dogs/")
            or not key.lower().endswith(SUFFIXES)
            or any(part in ("", ".", "..") for part in key.split("/"))):
        return None
    try:
        root = Path(settings.MEDIA_ROOT).resolve()
        original = Path(default_storage.path(key)).resolve()
        if not original.is_relative_to(root) or not original.is_file():
            return None
        stat = original.stat()
    except (OSError, ValueError, NotImplementedError):
        return None
    if not 0 < stat.st_size <= MAX_BYTES:
        return None
    fingerprint = hashlib.sha256(
        f"{key}\n{stat.st_size}\n{stat.st_mtime_ns}".encode()
    ).hexdigest()
    destination = root / "cca-photo-renditions" / "local-v1" / fingerprint[:2] / fingerprint / (variant + ".webp")
    return original, destination


def existing_preview(key, variant):
    paths = preview_paths(key, variant)
    return paths[1] if paths and paths[1].is_file() else None


def build_previews(key):
    pending = [(variant, preview_paths(key, variant)) for variant in WIDTHS]
    pending = [(variant, pair) for variant, pair in pending if pair and not pair[1].is_file()]
    if not pending:
        return 0
    original = pending[0][1][0]
    with Image.open(original) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError("Photo exceeds pixel bound")
        source.load()
        image = ImageOps.exif_transpose(source)
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        written = 0
        for variant, (_, destination) in pending:
            width = WIDTHS[variant]
            preview = image
            if image.width > width:
                preview = image.resize((width, max(1, round(image.height * width / image.width))), Image.Resampling.LANCZOS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".preview-", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    preview.save(stream, "WEBP", quality=79, method=4)
                if preview_paths(key, variant) != (original, destination):
                    raise ValueError("Original changed during preview generation")
                try:
                    os.link(tmp, destination)
                    written += 1
                except FileExistsError:
                    pass
            finally:
                Path(tmp).unlink(missing_ok=True)
    return written
