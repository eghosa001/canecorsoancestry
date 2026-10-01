import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, DogSource


FIELDS = [
    "id", "name", "gender", "father_name", "father_id", "mother_name", "mother_id",
    "pedigree_number", "titles", "extra_titles", "dob", "colour", "hd", "ed",
    "heart", "dsra_result", "dvl2_result", "dna_profile", "other_healthscores",
    "source_url", "scraped_at", "content_sha256",
]


class CaneCorsoArchiveImportTests(TestCase):
    def test_recent_import_includes_ancestors_and_is_idempotent(self):
        rows = [
            {"id": "1", "name": "Old Sire", "gender": "male", "dob": "2015/01/01"},
            {"id": "2", "name": "Old Dam", "gender": "female", "dob": "2016/01/01"},
            {
                "id": "3", "name": "Recent Dog", "gender": "female", "dob": "2024/02/03",
                "father_id": "1", "mother_id": "2",
                "source_url": "https://www.canecorsopedigree.com/view_dog?id=3",
            },
            {"id": "4", "name": "Unrelated Old Dog", "gender": "male", "dob": "2010/01/01"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            source = Path(handle.name)

        try:
            call_command(
                "import_canecorso_archive",
                source,
                start_year=2020,
                end_year=2026,
                publish=True,
                stdout=StringIO(),
            )
            call_command(
                "import_canecorso_archive",
                source,
                start_year=2020,
                end_year=2026,
                publish=True,
                stdout=StringIO(),
            )
        finally:
            source.unlink(missing_ok=True)

        dog = Dog.objects.get(name="Recent Dog")
        self.assertEqual(Dog.objects.count(), 3)
        self.assertEqual(dog.sire.name, "Old Sire")
        self.assertEqual(dog.dam.name, "Old Dam")
        self.assertTrue(dog.is_public)
        self.assertEqual(
            DogExternalKey.objects.filter(namespace="canecorsopedigree.com").count(), 3
        )
        self.assertEqual(DogSource.objects.count(), 3)


class CaneCorsoArchivePublishTests(TestCase):
    def test_publish_rerun_only_publishes_archive_created_dogs(self):
        existing = Dog.objects.create(name="Existing Canonical", slug="existing-canonical")
        DogExternalKey.objects.create(
            dog=existing, namespace="canecorsopedigree.com", key="9"
        )
        imported = Dog.objects.create(name="Imported", slug="ccp-10-imported")
        DogExternalKey.objects.create(
            dog=imported, namespace="canecorsopedigree.com", key="10"
        )

        rows = [
            {"id": "9", "name": "Existing Canonical", "dob": "2024/01/01"},
            {"id": "10", "name": "Imported", "dob": "2024/02/01"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            source = Path(handle.name)

        try:
            call_command(
                "import_canecorso_archive",
                source,
                start_year=2020,
                end_year=2026,
                publish=True,
                stdout=StringIO(),
            )
        finally:
            source.unlink(missing_ok=True)

        existing.refresh_from_db()
        imported.refresh_from_db()
        self.assertFalse(existing.is_public)
        self.assertTrue(imported.is_public)
