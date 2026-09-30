import hashlib
import hmac
import time
from urllib.parse import quote


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def gateway_signature(secret, method, key, timestamp, digest):
    message = f"{method.upper()}\n{key}\n{timestamp}\n{digest}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def media_signature(secret, key, expires):
    message = f"GET\n{key}\n{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_media_url(base_url, key, secret, ttl=300):
    expires = int(time.time()) + int(ttl)
    signature = media_signature(secret, key, expires)
    encoded = quote(key, safe="/")
    return (
        f"{base_url.rstrip('/')}/_media/{encoded}"
        f"?expires={expires}&signature={signature}"
    )
