"""Safeguards for the reviewed, explicit ten-dog merge allowlist."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.db import transaction

from registry.management.commands.reconcile_verified_coi_candidates import (
    REVIEWED_PAIRS,
)
from registry.models import (
    Dog, DogExternalKey, DogRegistration, DogSource, DogRedirect,
)


class VerifiedCOIReconciliationTests(TestCase):
    def setUp(self):
        self.slug, self.source_id, self.registration = REVIEWED_PAIRS[0]
        self.grandsire = Dog.objects.create(
            name="Ancestor 1", slug="coi-ancestor-one", is_public=True,
        )
        self.granddam = Dog.objects.create(
            name="Ancestor 2", slug="coi-ancestor-two", is_public=True,
        )
        self.canonical = Dog.objects.create(
            name="Mia Olimpo Osiride", slug=self.slug,
            sex=Dog.Sex.FEMALE, is_public=True,
        )
        self.archive = Dog.objects.create(
            name="MIA OLIMPO OSIRIDE", slug=f"ccp-{self.source_id}-{self.slug}",
            sex=Dog.Sex.FEMALE, is_public=True,
            sire=self.grandsire, dam=self.granddam,
        )
        DogExternalKey.objects.create(
            dog=self.canonical, namespace="bellissimo-geni", key=self.slug,
        )
        DogExternalKey.objects.create(
            dog=self.archive, namespace="canecorsopedigree.com", key=self.source_id,
        )
        DogRegistration.objects.create(
            dog=self.canonical, number="ROI 10/9253",
        )
        DogSource.objects.create(
            dog=self.archive, title="Source", source_type=DogSource.SourceType.PEDIGREE,
            raw_payload={"pedigree_number": "LO109253"},
        )

    def test_default_preview_does_not_write_records(self):
        call_command("reconcile_verified_coi_candidates", only=self.slug)
        self.canonical.refresh_from_db()
        self.assertIsNone(self.canonical.sire_id)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_apply_preserves_ancestry_and_is_idempotent(self):
        call_command("reconcile_verified_coi_candidates", only=self.slug, apply=True)
        self.canonical.refresh_from_db()
        self.assertEqual(self.canonical.sire_id, self.grandsire.pk)
        self.assertEqual(self.canonical.dam_id, self.granddam.pk)
        self.assertFalse(Dog.objects.filter(pk=self.archive.pk).exists())
        self.assertTrue(DogRedirect.objects.filter(
            old_slug=f"ccp-{self.source_id}-{self.slug}", dog=self.canonical,
        ).exists())
        call_command("reconcile_verified_coi_candidates", only=self.slug, apply=True)

    def test_discrepant_registration_blocks_mutation(self):
        DogRegistration.objects.filter(dog=self.canonical).update(
            number="ROI 88/999999",
        )
        with self.assertRaises(CommandError):
            call_command("reconcile_verified_coi_candidates", only=self.slug, apply=True)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_locked_or_unpublished_record_blocks_mutation(self):
        Dog.objects.filter(pk=self.archive.pk).update(is_public=False)
        with self.assertRaises(CommandError):
            call_command("reconcile_verified_coi_candidates", only=self.slug, apply=True)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_parent_pair_collision_is_blocked(self):
        Dog.objects.create(
            name="Conflict Child", slug="conflict-child",
            sire=self.canonical, dam=self.archive, is_public=True,
        )
        with self.assertRaisesMessage(CommandError, "parent-pair conflict"):
            call_command("reconcile_verified_coi_candidates", only=self.slug, apply=True)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_explicit_allowlist_excludes_disputed_pair(self):
        self.assertEqual(len(REVIEWED_PAIRS), 10)
        self.assertNotIn("faro-olimpo", [x[0] for x in REVIEWED_PAIRS])
