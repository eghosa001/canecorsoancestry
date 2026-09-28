import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, DogRegistration


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
