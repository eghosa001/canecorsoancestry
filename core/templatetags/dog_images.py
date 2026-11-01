"""Short-lived, directly signed CDN URLs for public dog photograph renditions.

Never use this on submitted evidence, medical documents, or other private files.
Original photographs remain reachable via the existing permission-checked media route.
"""
import hashlib
import hmac
import time
from urllib.parse import quote, unquote, urlsplit

from django import template
from django.conf import settings

register = template.Library()
PHOTO_PRESETS = {"thumb", "card", "portrait"}
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif")


@register.filter
def dog_photo(url, variant="card"):
    """Use a single signed R2 request instead of /media/ -> 302 -> R2.

    Only explicitly referenced dog photographs receive a rendition. Never
    derive a public image URL for a document or an arbitrary storage key.
    """
    source = str(url or "")
    if not source or variant not in PHOTO_PRESETS:
        return source
    parsed = urlsplit(source)
    # Source archive photos are external and are not in our R2 bucket.
    if parsed.scheme or parsed.netloc:
        return source
    if not parsed.path.startswith("/media/dogs/"):
        return source

    key = unquote(parsed.path[len("/media/"):])
    if (not key.startswith("dogs/") or ".." in key.split("/")
            or not key.lower().endswith(PHOTO_SUFFIXES)):
        return source

    base = str(getattr(settings, "MEDIA_EDGE_BASE_URL", "") or "").rstrip("/")
    signing_key = str(
        getattr(settings, "R2_GATEWAY_SIGNING_KEY", "")
        or getattr(settings, "SECRET_KEY", "")
    )
    if not base or not signing_key:
        return source

    # Minute boundaries keep preload URLs and image src/srcset identical,
    # while keeping links short-lived after a dog is made private.
    ttl = min(300, max(60, int(getattr(settings, "MEDIA_EDGE_URL_TTL", 300))))
    expires = ((int(time.time()) + ttl + 59) // 60) * 60
    message = f"GET\n{key}\n{variant}\n{expires}".encode()
    signature = hmac.new(signing_key.encode(), message, hashlib.sha256).hexdigest()
    return (
        f"{base}/_thumb/{quote(key, safe='/')}"
        f"?variant={variant}&expires={expires}&signature={signature}"
    )
