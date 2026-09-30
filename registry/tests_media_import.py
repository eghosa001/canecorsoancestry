import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from registry.models import Dog, DogExternalKey, DogImage


class BellissimoMediaImportTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(
            name="Media Dog",
            slug="media-dog",
            is_public=True,
        )
        DogExternalKey.objects.create(
            dog=self.dog,
            namespace="bellissimo-geni",
            key="media-dog",
        )

    def _manifest(self, items):
        payload = {"namespace": "bellissimo-geni", "items": items}
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        )
        with handle:
            json.dump(payload, handle)
        return Path(handle.name)

    def test_import_is_idempotent_and_assigns_primary(self):
        manifest = self._manifest(
            [
                {
                    "dog_external_key": "media-dog",
                    "r2_key": "dogs/bellissimo/main.webp",
                    "is_primary": True,
                    "sort_order": 0,
                },
                {
                    "dog_external_key": "media-dog",
                    "r2_key": "dogs/bellissimo/second.webp",
                    "is_primary": False,
                    "sort_order": 1,
                },
            ]
        )
        try:
            call_command("import_bellissimo_media", manifest, stdout=StringIO())
            call_command("import_bellissimo_media", manifest, stdout=StringIO())
        finally:
            manifest.unlink(missing_ok=True)

        self.assertEqual(DogImage.objects.count(), 2)
        self.assertTrue(
            DogImage.objects.get(image="dogs/bellissimo/main.webp").is_primary
        )
        self.assertFalse(
            DogImage.objects.get(image="dogs/bellissimo/second.webp").is_primary
        )

    def test_existing_primary_is_not_replaced(self):
        DogImage.objects.create(
            dog=self.dog,
            image="dogs/manual/current.webp",
            is_primary=True,
        )
        manifest = self._manifest(
            [
                {
                    "dog_external_key": "media-dog",
                    "r2_key": "dogs/bellissimo/imported.webp",
                    "is_primary": True,
                    "sort_order": 0,
                }
            ]
        )
        try:
            call_command("import_bellissimo_media", manifest, stdout=StringIO())
        finally:
            manifest.unlink(missing_ok=True)

        self.assertTrue(
            DogImage.objects.get(image="dogs/manual/current.webp").is_primary
        )
        self.assertFalse(
            DogImage.objects.get(image="dogs/bellissimo/imported.webp").is_primary
        )

    def test_dry_run_rolls_back(self):
        manifest = self._manifest(
            [
                {
                    "dog_external_key": "media-dog",
                    "r2_key": "dogs/bellissimo/dry.webp",
                    "is_primary": True,
                    "sort_order": 0,
                }
            ]
        )
        try:
            call_command(
                "import_bellissimo_media",
                manifest,
                dry_run=True,
                stdout=StringIO(),
            )
        finally:
            manifest.unlink(missing_ok=True)

        self.assertFalse(DogImage.objects.exists())
