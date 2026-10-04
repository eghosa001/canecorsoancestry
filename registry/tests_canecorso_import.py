import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, DogRegistration, DogSource, Kennel


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

    def test_repeated_explicit_kennel_suffixes_are_linked(self):
        rows = [
            {
                "id": "11",
                "name": "BATMAN NASKA CANE CORSO KENNEL",
                "gender": "male",
                "dob": "2024/01/01",
            },
            {
                "id": "12",
                "name": "BLUE SIRIUS NASKA CANE CORSO KENNEL",
                "gender": "male",
                "dob": "2024/01/02",
            },
            {
                "id": "13",
                "name": "AMAZON NASKA CANE CORSO KENNEL",
                "gender": "female",
                "dob": "2024/01/03",
            },
            {
                "id": "14",
                "name": "SOLO ONE OFF KENNEL",
                "gender": "female",
                "dob": "2024/01/04",
            },
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            source = Path(handle.name)

        try:
            call_command(
                "import_canecorso_archive",
                source,
                start_year=2020,
                end_year=2026,
                stdout=StringIO(),
            )
        finally:
            source.unlink(missing_ok=True)

        kennel = Kennel.objects.get(name="Naska Cane Corso Kennel")
        self.assertEqual(Dog.objects.filter(kennel=kennel).count(), 3)
        self.assertIsNone(Dog.objects.get(name="SOLO ONE OFF KENNEL").kennel)

    def test_composite_registration_fragment_reuses_canonical_dog(self):
        existing = Dog.objects.create(
            name="Hermes Di Casa Lepore (Vegas)",
            slug="hermes",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        DogRegistration.objects.create(
            dog=existing,
            authority=None,
            number="JR 700381 Cc",
        )
        rows = [{
            "id": "75282",
            "name": "HERMES DI CASA LEPORE (VEGAS)",
            "gender": "male",
            "dob": "2024/09/23",
            "pedigree_number": "LO16196852 ; jr-700381 cc",
        }]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
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

        self.assertEqual(Dog.objects.count(), 1)
        self.assertTrue(
            DogExternalKey.objects.filter(
                namespace="canecorsopedigree.com", key="75282", dog=existing
            ).exists()
        )

    def test_registration_fragment_requires_same_name(self):
        existing = Dog.objects.create(
            name="Tyson",
            slug="tyson",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        DogRegistration.objects.create(
            dog=existing,
            authority=None,
            number="JR 70447 Cc",
        )
        rows = [{
            "id": "18924",
            "name": "ZAHUR CUSTODI NOS",
            "gender": "male",
            "dob": "2024/01/01",
            "pedigree_number": "JR 70447 Cc ; JR 80112 Cc",
        }]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
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

        self.assertEqual(Dog.objects.count(), 2)
        imported = Dog.objects.get(
            external_keys__namespace="canecorsopedigree.com",
            external_keys__key="18924",
        )
        self.assertEqual(imported.name, "ZAHUR CUSTODI NOS")
        self.assertNotEqual(imported.pk, existing.pk)

