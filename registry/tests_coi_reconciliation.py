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


class COILineageDiagnosticsTests(TestCase):
    def test_published_common_ancestors_report_actual_kinship(self):
        from pedigrees.services import coi_linkage_summary
        common = Dog.objects.create(name="Review Common", slug="review-common", is_public=True)
        sire = Dog.objects.create(name="Review Sire", slug="review-sire", sire=common, is_public=True)
        dam = Dog.objects.create(name="Review Dam", slug="review-dam", sire=common, is_public=True)
        child = Dog.objects.create(name="Review Child", slug="review-child", sire=sire, dam=dam, is_public=True)
        summary = coi_linkage_summary(child)
        self.assertEqual(summary["status"], "estimated")
        self.assertAlmostEqual(summary["coi_percent"], 12.5)
        self.assertEqual((summary["sire_records"], summary["dam_records"], summary["shared_ancestors"]), (2, 2, 1))

    def test_private_shared_ancestor_not_included_in_public_diagnostics(self):
        from pedigrees.services import coi_linkage_summary
        hidden = Dog.objects.create(name="Private Common", slug="private-common-review", is_public=False)
        sire = Dog.objects.create(name="Public Sire", slug="public-sire-review", sire=hidden, is_public=True)
        dam = Dog.objects.create(name="Public Dam", slug="public-dam-review", sire=hidden, is_public=True)
        child = Dog.objects.create(name="Review No Public Common", slug="review-no-public-common", sire=sire, dam=dam, is_public=True)
        summary = coi_linkage_summary(child)
        self.assertEqual(summary["coi_percent"], 0)
        self.assertEqual(summary["shared_ancestors"], 0)
        self.assertEqual((summary["sire_records"], summary["dam_records"]), (1, 1))

    def test_missing_published_parent_is_not_misrepresented_as_zero(self):
        from pedigrees.services import coi_linkage_summary
        sire = Dog.objects.create(name="Known Review Sire", slug="known-review-sire", is_public=True)
        child = Dog.objects.create(name="Incomplete Review Child", slug="incomplete-review-child", sire=sire, is_public=True)
        summary = coi_linkage_summary(child)
        self.assertEqual(summary["status"], "insufficient")
        self.assertIsNone(summary["coi_percent"])

    def test_review_search_requires_staff_and_only_shows_public_dogs(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        editor = get_user_model().objects.create_superuser(
            username="coi-review-admin", email="coi-review@example.test", password="test-admin-password-2026"
        )
        public = Dog.objects.create(name="COI Audit Public", slug="coi-audit-public", is_public=True)
        Dog.objects.create(name="COI Audit Hidden", slug="coi-audit-hidden", is_public=False)
        url = reverse("accounts:data-health")
        denied = self.client.get(url, {"coi_q": "COI Audit"})
        self.assertNotEqual(denied.status_code, 200)
        self.client.force_login(editor)
        response = self.client.get(url, {"coi_q": "COI Audit"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["dog"].pk for row in response.context["coi_matches"]], [public.pk])
        self.assertContains(response, "Not enough ancestry")
        self.assertNotContains(response, "COI Audit Hidden")
