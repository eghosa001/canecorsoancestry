"""Focused, evidence-backed registry reconciliation tests."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from registry.models import (
    Dog, DogExternalKey, DogRegistration, DogSource, DogRedirect,
)
from pedigrees.services import inbreeding_coefficient


class CanonicalCOIRepairTests(TestCase):
    def setUp(self):
        shared = Dog.objects.create(name="Shared", slug="coi-fixture-shared", is_public=True)
        grandparent = Dog.objects.create(
            name="Tocco Grandparent", slug="coi-fixture-grandparent",
            sire=shared, is_public=True,
        )
        other = Dog.objects.create(
            name="Tocco Other Grandparent", slug="coi-fixture-other",
            is_public=True,
        )
        self.archive = Dog.objects.create(
            name="TOCCO OF REVENGE DELLA VALLE DEI LORD",
            slug="ccp-27801-tocco-of-revenge-della-valle-dei-lord",
            sex=Dog.Sex.MALE, is_public=True,
            sire=grandparent, dam=other,
        )
        self.canonical = Dog.objects.create(
            name="Tocco Of Revenge Della Valle Dei Lord",
            slug="tocco-of-revenge-della-valle-dei-lord",
            sex=Dog.Sex.MALE, is_public=True,
        )
        DogExternalKey.objects.create(
            dog=self.archive, namespace="canecorsopedigree.com", key="27801",
        )
        DogExternalKey.objects.create(
            dog=self.canonical, namespace="bellissimo-geni", key="tocco-of-revenge-della-valle-dei-lord",
        )
        DogRegistration.objects.create(dog=self.canonical, number="ROI 12/152913")
        DogSource.objects.create(
            dog=self.archive, source_type=DogSource.SourceType.PEDIGREE,
            title="Source", raw_payload={"pedigree_number": "LO12152913"},
        )
        dam = Dog.objects.create(name="Fixture Dam", slug="coi-fixture-dam", sire=shared, is_public=True)
        self.child = Dog.objects.create(
            name="Fixture Child", slug="coi-fixture-child",
            sire=self.canonical, dam=dam, is_public=True,
        )

    def test_dry_run_does_not_change_parentage(self):
        call_command("reconcile_known_ancestors", only="tocco-of-revenge-della-valle-dei-lord")
        self.canonical.refresh_from_db()
        self.assertIsNone(self.canonical.sire_id)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_merges_verified_duplicates_and_preserves_redirect_and_coi(self):
        self.assertEqual(inbreeding_coefficient(self.child), 0)
        call_command("reconcile_known_ancestors", only="tocco-of-revenge-della-valle-dei-lord", apply=True)
        self.canonical.refresh_from_db()
        self.assertEqual(self.canonical.sire_id, self.archive.sire_id)
        self.assertFalse(Dog.objects.filter(pk=self.archive.pk).exists())
        self.assertTrue(DogRedirect.objects.filter(old_slug=self.archive.slug, dog=self.canonical).exists())
        self.assertGreater(inbreeding_coefficient(self.child), 0)
        call_command("reconcile_known_ancestors", only="tocco-of-revenge-della-valle-dei-lord", apply=True)

    def test_rejects_registration_mismatch_without_deleting_anything(self):
        DogRegistration.objects.filter(dog=self.canonical).update(number="ROI 12/999999")
        with self.assertRaises(CommandError):
            call_command("reconcile_known_ancestors", only="tocco-of-revenge-della-valle-dei-lord", apply=True)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())
