from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import Dog, DogExternalKey, Kennel


class KennelInferenceTests(TestCase):
    def _archive_dog(self, key, name, *, kennel=None):
        dog = Dog.objects.create(
            name=name,
            slug=f"test-{key}",
            sex=Dog.Sex.UNKNOWN,
            kennel=kennel,
            is_public=True,
        )
        DogExternalKey.objects.create(
            dog=dog,
            namespace="canecorsopedigree.com",
            key=str(key),
        )
        return dog

    def test_infers_repeated_prefix_and_suffix_without_overwriting_existing(self):
        costa = [
            self._archive_dog("1", "COSTA DINOS JOHN"),
            self._archive_dog("2", "COSTA DINOS REX"),
            self._archive_dog("3", "COSTA DINOS ARIA"),
        ]
        custodi = [
            self._archive_dog("4", "MAYA CUSTODI NOS"),
            self._archive_dog("5", "BRANCO CUSTODI NOS"),
            self._archive_dog("6", "TARA CUSTODI NOS"),
        ]

        manual = Kennel.objects.create(name="Manual Kennel", slug="manual-kennel")
        protected = self._archive_dog("7", "COSTA DINOS EXISTING", kennel=manual)

        generic = [
            self._archive_dog("8", "ARES ALPHA"),
            self._archive_dog("9", "ARES BETA"),
            self._archive_dog("10", "ARES GAMMA"),
        ]

        call_command(
            "infer_kennels_from_archive",
            apply=True,
            min_occurrences=3,
            min_single_occurrences=3,
            stdout=StringIO(),
        )

        costa_kennel = Kennel.objects.get(name="Costa Dinos")
        custodi_kennel = Kennel.objects.get(name="Custodi Nos")

        for dog in costa:
            dog.refresh_from_db()
            self.assertEqual(dog.kennel, costa_kennel)

        for dog in custodi:
            dog.refresh_from_db()
            self.assertEqual(dog.kennel, custodi_kennel)

        protected.refresh_from_db()
        self.assertEqual(protected.kennel, manual)

        for dog in generic:
            dog.refresh_from_db()
            self.assertIsNone(dog.kennel)

    def test_dry_analysis_does_not_change_database(self):
        for key, name in (
            ("11", "COSTA DINOS JOHN"),
            ("12", "COSTA DINOS REX"),
            ("13", "COSTA DINOS ARIA"),
        ):
            self._archive_dog(key, name)

        call_command(
            "infer_kennels_from_archive",
            min_occurrences=3,
            min_single_occurrences=3,
            stdout=StringIO(),
        )

        self.assertFalse(Kennel.objects.exists())
        self.assertEqual(Dog.objects.filter(kennel__isnull=False).count(), 0)
