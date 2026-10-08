from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Dog, DogImage, DogSource, Kennel, Litter
from .querysets import with_displayable_images
from .services import _canonical_litter_conflict


class CanonicalLitterInvariantTests(TestCase):
    def setUp(self):
        self.sire = Dog.objects.create(
            name="Invariant Sire",
            slug="invariant-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Invariant Dam",
            slug="invariant-dam",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )
        self.dob = date(2025, 5, 1)

    def test_database_rejects_second_litter_for_same_parents_and_dob(self):
        Litter.objects.create(
            code="INV-001",
            sire=self.sire,
            dam=self.dam,
            date_of_birth=self.dob,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Litter.objects.create(
                    code="INV-002",
                    sire=self.sire,
                    dam=self.dam,
                    date_of_birth=self.dob,
                )

    def test_application_guard_is_independent_of_kennel(self):
        first_kennel = Kennel.objects.create(
            name="Invariant Kennel One",
            slug="invariant-kennel-one",
        )
        second_kennel = Kennel.objects.create(
            name="Invariant Kennel Two",
            slug="invariant-kennel-two",
        )
        litter = Litter.objects.create(
            code="INV-003",
            kennel=first_kennel,
            sire=self.sire,
            dam=self.dam,
            date_of_birth=self.dob,
        )

        with transaction.atomic():
            conflict = _canonical_litter_conflict(
                sire=self.sire,
                dam=self.dam,
                date_of_birth=self.dob,
            )

        self.assertEqual(conflict, litter)
        self.assertNotEqual(litter.kennel, second_kennel)


class PublicDiscoveryPhotoInvariantTests(TestCase):
    def test_displayable_scope_includes_managed_and_trusted_source_photos_only(self):
        managed = Dog.objects.create(
            name="Managed Photo Dog",
            slug="managed-photo-dog",
            is_public=True,
        )
        trusted = Dog.objects.create(
            name="Trusted Source Dog",
            slug="trusted-source-dog",
            is_public=True,
        )
        hidden = Dog.objects.create(
            name="Pedigree Only Dog",
            slug="pedigree-only-dog",
            is_public=True,
        )
        untrusted = Dog.objects.create(
            name="Untrusted Source Dog",
            slug="untrusted-source-photo-dog",
            is_public=True,
        )
        DogImage.objects.create(dog=managed, image="dogs/managed.jpg")
        DogSource.objects.create(
            dog=trusted,
            raw_payload={
                "image_url": "https://canecorsopedigree.com/static/images/animal/trusted.jpg"
            },
        )
        DogSource.objects.create(
            dog=untrusted,
            raw_payload={"image_url": "https://example.com/untrusted.jpg"},
        )

        discovered = set(
            with_displayable_images(Dog.objects.filter(is_public=True))
            .values_list("pk", flat=True)
        )

        self.assertIn(managed.pk, discovered)
        self.assertIn(trusted.pk, discovered)
        self.assertNotIn(hidden.pk, discovered)
        self.assertNotIn(untrusted.pk, discovered)


class ProductionInvariantCommandTests(TestCase):
    def test_command_passes_for_clean_data(self):
        out = StringIO()
        call_command("audit_production_invariants", "--fail-on-critical", stdout=out)
        self.assertIn("critical_count: 0", out.getvalue())

    def test_command_fails_for_case_insensitive_duplicate_kennel_names(self):
        Kennel.objects.create(name="Duplicate Kennel", slug="duplicate-kennel-one")
        Kennel.objects.create(name="duplicate kennel", slug="duplicate-kennel-two")

        with self.assertRaises(CommandError):
            call_command(
                "audit_production_invariants",
                "--fail-on-critical",
                stdout=StringIO(),
            )
