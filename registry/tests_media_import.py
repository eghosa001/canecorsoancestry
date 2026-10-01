import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

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



class CaneCorsoArchiveImageImportTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(
            name="Archive Dog",
            slug="archive-dog",
            is_public=True,
        )
        DogExternalKey.objects.create(
            dog=self.dog,
            namespace="canecorsopedigree.com",
            key="12345",
        )

    def test_physical_file_is_imported_even_when_csv_image_file_is_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "dogs.csv"
            images = root / "images"
            images.mkdir()
            source.write_text(
                "id,name,image_url,image_file\n"
                "12345,Archive Dog,https://example.invalid/photo.jpg,\n",
                encoding="utf-8",
            )
            # Name deliberately differs from any CSV mapping. Numeric source ID is
            # the authoritative association produced by the scraper.
            (images / "12345_COMPLETELY_DIFFERENT_NAME.jpg").write_bytes(
                b"not-a-real-jpeg-but-nonempty"
            )
            media_root = root / "media"
            with override_settings(
                MEDIA_ROOT=media_root,
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage"
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                    },
                },
            ):
                call_command(
                    "import_canecorso_archive_images",
                    source,
                    images,
                    stdout=StringIO(),
                )

        image = DogImage.objects.get(dog=self.dog)
        self.assertTrue(image.is_primary)
        self.assertIn("dogs/archive/012/12345.jpg", image.image.name)
        self.assertTrue(image.caption.startswith("Archived source photo"))

    def test_existing_curated_image_wins_over_archive_file(self):
        DogImage.objects.create(
            dog=self.dog,
            image="dogs/manual/curated.webp",
            is_primary=True,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "dogs.csv"
            images = root / "images"
            images.mkdir()
            source.write_text(
                "id,name,image_url,image_file\n"
                "12345,Archive Dog,,,\n",
                encoding="utf-8",
            )
            (images / "12345_OTHER_NAME.jpg").write_bytes(b"archive-copy")
            with override_settings(
                MEDIA_ROOT=root / "media",
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage"
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                    },
                },
            ):
                call_command(
                    "import_canecorso_archive_images",
                    source,
                    images,
                    stdout=StringIO(),
                )

        self.assertEqual(DogImage.objects.filter(dog=self.dog).count(), 1)
        self.assertEqual(
            DogImage.objects.get(dog=self.dog).image.name,
            "dogs/manual/curated.webp",
        )
