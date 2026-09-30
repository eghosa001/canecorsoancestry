import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

from core.cloudflare_media import gateway_signature, sha256_hex


@deconstructible
class CloudflareR2GatewayStorage(Storage):
    """Use a signed Cloudflare Worker gateway for private R2 operations."""

    def __init__(self, base_url=None, timeout=30):
        self.base_url = (
            base_url
            or getattr(settings, "R2_GATEWAY_URL", "")
        ).rstrip("/")
        self.timeout = timeout
        if not self.base_url:
            raise RuntimeError("R2_GATEWAY_URL is required for R2 media storage.")

    def _url(self, name):
        encoded = urllib.parse.quote(name, safe="/")
        return f"{self.base_url}/_r2/{encoded}"

    def _request(self, name, *, method, data=None, content_type=None):
        body = data or b""
        digest = sha256_hex(body)
        timestamp = str(int(time.time()))
        signature = gateway_signature(
            settings.SECRET_KEY,
            method,
            name,
            timestamp,
            digest,
        )
        headers = {
            "X-R2-Timestamp": timestamp,
            "X-R2-Content-SHA256": digest,
            "X-R2-Signature": signature,
        }
        if content_type:
            headers["Content-Type"] = content_type

        request = urllib.request.Request(
            self._url(name),
            data=body if method == "PUT" else None,
            method=method,
            headers=headers,
        )
        try:
            return urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(name) from exc
            raise

    def _save(self, name, content):
        return self.save_exact(name, content)

    def save_exact(self, name, content):
        data = content.read()
        content_type = (
            getattr(content, "content_type", None)
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        with self._request(
            name,
            method="PUT",
            data=data,
            content_type=content_type,
        ):
            pass
        return name

    def _open(self, name, mode="rb"):
        with self._request(name, method="GET") as response:
            return ContentFile(response.read(), name=name)

    def exists(self, name):
        try:
            with self._request(name, method="HEAD"):
                return True
        except FileNotFoundError:
            return False

    def delete(self, name):
        try:
            with self._request(name, method="DELETE"):
                pass
        except FileNotFoundError:
            pass

    def size(self, name):
        try:
            with self._request(name, method="HEAD") as response:
                return int(response.headers["Content-Length"])
        except FileNotFoundError:
            raise

    def url(self, name):
        return "/media/" + urllib.parse.quote(name, safe="/")
