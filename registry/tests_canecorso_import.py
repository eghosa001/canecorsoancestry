import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, DogRegistration, DogSource


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
                stdout=StringIO(),
            )
            self.assertFalse(Dog.objects.get(name="Recent Dog").is_public)
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


    def test_registration_match_does_not_merge_different_dog_identity(self):
        existing = Dog.objects.create(
            name="Sforza Ludovico II Imperatore",
            slug="sforza-ludovico-ii-imperatore",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        DogRegistration.objects.create(
            dog=existing,
            authority=None,
            number="JR 80580 Cc",
        )

        rows = [
            {
                "id": "26289",
                "name": "SFORZA LUDOVICO",
                "gender": "male",
                "dob": "2009/07/21",
                "pedigree_number": "JR 80580 Cc",
            },
            {
                "id": "99999",
                "name": "Recent Child",
                "gender": "female",
                "dob": "2025/02/03",
                "father_id": "26289",
            },
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

        ludovico = DogExternalKey.objects.get(
            namespace="canecorsopedigree.com",
            key="26289",
        ).dog
        self.assertNotEqual(ludovico.pk, existing.pk)
        self.assertEqual(ludovico.name, "SFORZA LUDOVICO")
        self.assertEqual(Dog.objects.get(name="Recent Child").sire, ludovico)
        self.assertEqual(existing.name, "Sforza Ludovico II Imperatore")
