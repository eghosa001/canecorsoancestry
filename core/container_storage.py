import mimetypes
import urllib.error
import urllib.parse
import urllib.request

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class CloudflareR2BridgeStorage(Storage):
    """Django storage backed by R2 through an internal Container outbound bridge."""

    def __init__(self, base_url=None):
        from django.conf import settings

        self.base_url = (
            base_url
            or getattr(settings, "R2_BRIDGE_URL", "")
        ).rstrip("/")
        if not self.base_url:
            raise RuntimeError("R2_BRIDGE_URL is required for container storage.")

    def _url(self, name):
        encoded = urllib.parse.quote(name, safe="/")
        return f"{self.base_url}/media/{encoded}"

    def _request(self, name, *, method, data=None, content_type=None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self._url(name),
            data=data,
            method=method,
            headers=headers,
        )
        try:
            return urllib.request.urlopen(request, timeout=30)
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
        request = urllib.request.Request(self._url(name), method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=15):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    def delete(self, name):
        request = urllib.request.Request(self._url(name), method="DELETE")
        try:
            with urllib.request.urlopen(request, timeout=15):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def size(self, name):
        request = urllib.request.Request(self._url(name), method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return int(response.headers["Content-Length"])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(name) from exc
            raise

    def url(self, name):
        return "/media/" + urllib.parse.quote(name, safe="/")
