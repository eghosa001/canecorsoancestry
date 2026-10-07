import json
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
            getattr(settings, "R2_GATEWAY_SIGNING_KEY", settings.SECRET_KEY),
            method,
            name,
            timestamp,
            digest,
        )
        headers = {
            "X-R2-Timestamp": timestamp,
            "X-R2-Content-SHA256": digest,
            "X-R2-Signature": signature,
            # Cloudflare can reject Python's default urllib identity before a
            # workers.dev request reaches the Worker. Use an explicit normal
            # HTTPS client identity for this private signed server-to-server path.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36 "
                "CaneCorsoAncestry-Media/1.0"
            ),
            "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
        }
        if content_type:
            headers["Content-Type"] = content_type

        retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
        attempts = 3
        for attempt in range(attempts):
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
                if exc.code not in retryable_statuses or attempt == attempts - 1:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == attempts - 1:
                    raise

            time.sleep(0.25 * (2 ** attempt))

        raise RuntimeError("R2 gateway request retry loop exited unexpectedly.")

    def _save(self, name, content):
        return self.save_exact(name, content)

    def save_exact(self, name, content):
        data = content.read()
        content_type = (
            getattr(content, "content_type", None)
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        try:
            with self._request(
                name,
                method="PUT",
                data=data,
                content_type=content_type,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise OSError("R2 upload returned an invalid verification response.") from exc

        try:
            stored_size = int(payload.get("size", -1))
        except (TypeError, ValueError) as exc:
            raise OSError("R2 upload returned an invalid stored size.") from exc

        if (
            payload.get("status") != "stored"
            or payload.get("r2_verified") is not True
            or stored_size != len(data)
        ):
            raise OSError("R2 could not verify the uploaded file.")

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
