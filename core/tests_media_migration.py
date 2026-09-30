import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from core.media_migration import body_sha256, migration_signature
from registry.models import Dog, DogImage


class FakeExactStorage:
    def __init__(self):
        self.objects = {}

    def exists(self, name):
        return name in self.objects

    def size(self, name):
        return len(self.objects[name])

    def open(self, name, mode="rb"):
        if name not in self.objects:
            raise FileNotFoundError(name)
        return ContentFile(self.objects[name], name=name)

    def save_exact(self, name, content):
        self.objects[name] = content.read()
        return name


@override_settings(MEDIA_MIGRATION_ENABLED=True, SECRET_KEY="migration-test-secret")
class CloudflareMediaImportTests(TestCase):
    def setUp(self):
        self.storage = FakeExactStorage()
        self.dog = Dog.objects.create(
            name="Migration Dog",
            slug="migration-dog",
            is_public=False,
        )
        self.path = "dogs/2026/09/migration.jpg"
        DogImage.objects.create(dog=self.dog, image=self.path)

    def _headers(self, body, *, path=None, timestamp=None, signature=None):
        path = path or self.path
        timestamp = str(timestamp or int(time.time()))
        digest = body_sha256(body)
        signature = signature or migration_signature(
            "migration-test-secret",
            timestamp,
            path,
            digest,
        )
        return {
            "X-Migration-Timestamp": timestamp,
            "X-Migration-Signature": signature,
        }

    def _post(self, body, *, path=None, headers=None):
        path = path or self.path
        return self.client.post(
            f"/internal/media-import/{path}",
            data=body,
            content_type="application/octet-stream",
            headers=headers or self._headers(body, path=path),
        )

    @patch("core.media_views.default_storage")
    def test_valid_import_writes_exact_key_and_verifies_hash(self, mocked_storage):
        mocked_storage.exists.side_effect = self.storage.exists
        mocked_storage.size.side_effect = self.storage.size
        mocked_storage.open.side_effect = self.storage.open
        mocked_storage.save_exact.side_effect = self.storage.save_exact

        body = b"original-dog-photo"
        response = self._post(body)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.storage.objects[self.path], body)
        self.assertEqual(response.json()["path"], self.path)
        self.assertEqual(response.json()["size"], len(body))
        self.assertEqual(response.json()["sha256"], body_sha256(body))

    @patch("core.media_views.default_storage")
    def test_identical_existing_object_is_not_rewritten(self, mocked_storage):
        body = b"already-copied"
        self.storage.objects[self.path] = body
        mocked_storage.exists.side_effect = self.storage.exists
        mocked_storage.size.side_effect = self.storage.size
        mocked_storage.open.side_effect = self.storage.open
        mocked_storage.save_exact.side_effect = self.storage.save_exact

        response = self._post(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "exists")
        mocked_storage.save_exact.assert_not_called()

    @patch("core.media_views.default_storage")
    def test_same_size_different_object_is_replaced(self, mocked_storage):
        old = b"old-content"
        new = b"new-content"
        self.assertEqual(len(old), len(new))
        self.storage.objects[self.path] = old
        mocked_storage.exists.side_effect = self.storage.exists
        mocked_storage.size.side_effect = self.storage.size
        mocked_storage.open.side_effect = self.storage.open
        mocked_storage.save_exact.side_effect = self.storage.save_exact

        response = self._post(new)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.storage.objects[self.path], new)

    def test_unknown_database_path_is_not_importable(self):
        path = "documents/not-referenced.pdf"
        body = b"not allowed"
        response = self._post(
            body,
            path=path,
            headers=self._headers(body, path=path),
        )
        self.assertEqual(response.status_code, 404)

    def test_bad_signature_is_forbidden(self):
        body = b"evidence"
        response = self._post(
            body,
            headers=self._headers(body, signature="0" * 64),
        )
        self.assertEqual(response.status_code, 403)

    def test_stale_signature_is_forbidden(self):
        body = b"evidence"
        stale = int(time.time()) - 3600
        response = self._post(
            body,
            headers=self._headers(body, timestamp=stale),
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(MEDIA_MIGRATION_ENABLED=False)
    def test_import_endpoint_is_hidden_when_migration_disabled(self):
        body = b"evidence"
        response = self._post(body)
        self.assertEqual(response.status_code, 404)
