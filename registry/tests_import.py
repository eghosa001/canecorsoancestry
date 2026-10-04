import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, DogRegistration, DogSource, Kennel


class BellissimoImportTests(TestCase):
    def test_import_is_idempotent_and_keeps_drafts_private(self):
        payload = {
            "schemaVersion": 4,
            "dogs": [
                {"id": "sire", "name": "Sire", "sex": "Male", "group": "ancestor"},
                {
                    "id": "dam",
                    "name": "Dam",
                    "sex": "Female",
                    "group": "ancestor",
                    "publishStatus": "draft",
                },
                {
                    "id": "child",
                    "name": "Child",
                    "sex": "Male",
                    "group": "current",
                    "sireId": "sire",
                    "damId": "dam",
                    "registration": "TEST 123",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            source = Path(handle.name)

        try:
            call_command("import_bellissimo", source, stdout=StringIO())
            call_command("import_bellissimo", source, stdout=StringIO())
        finally:
            source.unlink(missing_ok=True)

        child = Dog.objects.get(slug="child")
        self.assertEqual(Dog.objects.count(), 3)
        self.assertEqual(child.sire.name, "Sire")
        self.assertEqual(child.dam.name, "Dam")
        self.assertFalse(child.dam.is_public)
        self.assertEqual(DogExternalKey.objects.count(), 3)
        self.assertIsNone(DogRegistration.objects.get(dog=child).authority)



    def test_ludovico_records_remain_distinct(self):
        payload = {
            "schemaVersion": 5,
            "dogs": [
                {
                    "id": "sforza-ludovico",
                    "name": "SFORZA LUDOVICO",
                    "sex": "Male",
                    "group": "ancestor",
                    "registration": "JR 80580 Cc",
                },
                {
                    "id": "sforza-ludovico-ii-imperatore",
                    "name": "Sforza Ludovico II Imperatore",
                    "sex": "Male",
                    "group": "ancestor",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            source = Path(handle.name)

        try:
            call_command("import_bellissimo", source, stdout=StringIO())
        finally:
            source.unlink(missing_ok=True)

        ludovico = Dog.objects.get(slug="sforza-ludovico")
        ludovico_ii = Dog.objects.get(slug="sforza-ludovico-ii-imperatore")
        self.assertNotEqual(ludovico.pk, ludovico_ii.pk)
        self.assertEqual(ludovico_ii.name, "Sforza Ludovico II Imperatore")
        self.assertEqual(DogRegistration.objects.get(dog=ludovico).number, "JR 80580 Cc")
        self.assertFalse(DogRegistration.objects.filter(dog=ludovico_ii).exists())


class BellissimoPuppyImportTests(TestCase):
    def test_verified_puppy_import_is_idempotent_and_links_parents(self):
        kennel = Kennel.objects.create(
            name="Bellissimo Geni",
            slug="bellissimo-geni",
            country="Nigeria",
        )
        sire = Dog.objects.create(
            name="Branco Custodi Nos",
            slug="branco-parent-test",
            sex=Dog.Sex.MALE,
            kennel=kennel,
        )
        dam = Dog.objects.create(
            name="Anthie Custodi Nos",
            slug="anthie-parent-test",
            sex=Dog.Sex.FEMALE,
            kennel=kennel,
        )
        DogExternalKey.objects.create(
            dog=sire, namespace="bellissimo-geni", key="branco-custodi-nos"
        )
        DogExternalKey.objects.create(
            dog=dam, namespace="bellissimo-geni", key="anthie-custodi-nos"
        )

        payload = {
            "schemaVersion": 1,
            "puppies": [
                {
                    "id": "verified-puppy",
                    "name": "Verified Puppy",
                    "sex": "Female",
                    "dateOfBirth": "2025-08-02",
                    "colour": "Brindle",
                    "sireId": "branco-custodi-nos",
                    "damId": "anthie-custodi-nos",
                    "status": "AVAILABLE",
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            source = Path(handle.name)

        try:
            call_command("import_bellissimo_puppies", source, stdout=StringIO())
            call_command("import_bellissimo_puppies", source, stdout=StringIO())
        finally:
            source.unlink(missing_ok=True)

        puppy = Dog.objects.get(name="Verified Puppy")
        self.assertEqual(puppy.sire, sire)
        self.assertEqual(puppy.dam, dam)
        self.assertEqual(puppy.kennel, kennel)
        self.assertTrue(puppy.is_public)
        self.assertEqual(
            DogExternalKey.objects.filter(
                namespace="bellissimo-geni-puppies",
                key="verified-puppy",
            ).count(),
            1,
        )
        self.assertTrue(
            DogSource.objects.filter(
                dog=puppy,
                source_type=DogSource.SourceType.BREEDER,
            ).exists()
        )
