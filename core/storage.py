from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from urllib.parse import quote


@deconstructible
class CloudflareR2Storage(Storage):
    """Django storage backed by a Cloudflare R2 Worker binding."""

    def _bucket(self):
        from workers import env

        return env.MEDIA_BUCKET

    def _run(self, awaitable):
        from pyodide.ffi import run_sync

        return run_sync(awaitable)

    def _save(self, name, content):
        from pyodide.ffi import to_js

        data = content.read()
        self._run(self._bucket().put(name, to_js(data)))
        return name

    def _open(self, name, mode="rb"):
        from js import Uint8Array

        obj = self._run(self._bucket().get(name))
        if obj is None:
            raise FileNotFoundError(name)
        array_buffer = self._run(obj.arrayBuffer())
        data = bytes(Uint8Array.new(array_buffer).to_py())
        return ContentFile(data, name=name)

    def exists(self, name):
        return self._run(self._bucket().head(name)) is not None

    def delete(self, name):
        self._run(self._bucket().delete(name))

    def size(self, name):
        obj = self._run(self._bucket().head(name))
        if obj is None:
            raise FileNotFoundError(name)
        return int(obj.size)

    def url(self, name):
        return "/media/" + quote(name, safe="/")
