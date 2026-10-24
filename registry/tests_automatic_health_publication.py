"""Every public dog shows approved health results automatically, without fake attestations."""
from importlib import import_module

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .models import (
    Dog, DogDocument, BreedDNAReport, HealthRecord,
    ModerationAudit, VerificationState,
)


class AutomaticHealthPublicationTests(TestCase):
    def setUp(self):
        self.first = Dog.objects.create(name="Health first dog", slug="health-first-dog", is_public=True)
        self.second = Dog.objects.create(name="Health second dog", slug="health-second-dog", is_public=True)

    def test_auto_publish_backfill_covers_multiple_dogs_not_private_or_consentless_reports(self):
        first = HealthRecord.objects.create(
            dog=self.first, test_type="DSRA", result="Clear",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        second = HealthRecord.objects.create(
            dog=self.second, test_type="Elbow score", result="ED-0",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        pending = HealthRecord.objects.create(
            dog=self.second, test_type="Unreviewed marker", result="Carrier",
            verification_state=VerificationState.COMMUNITY, is_public=False,
        )
        withheld = HealthRecord.objects.create(
            dog=self.first, test_type="CMR1", result="Carrier",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        ModerationAudit.objects.create(
            dog=self.first, action=ModerationAudit.Action.VERIFICATION,
            summary={"kind": "health_summary_visibility", "health_record_id": withheld.pk, "public": False},
        )
        document = DogDocument.objects.create(
            dog=self.first, title="Private breed certificate", document_type="dna",
            file="private/staff-only-breed-report.pdf", is_public=False, staff_review_only=True,
        )
        breed = HealthRecord.objects.create(
            dog=self.first, test_type="DNA breed composition", result="100% Cane Corso",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        BreedDNAReport.objects.create(
            health_record=breed, evidence_document=document, provider="Embark",
            cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=False,
        )
        migration = import_module("registry.migrations.0021_auto_publish_approved_health")
        from django.apps import apps
        editor = type("MigrationEditor", (), {"connection": connection})()
        migration.publish_approved_health_summaries(apps, editor)
        for record in (first, second, pending, withheld, breed):
            record.refresh_from_db()
        self.assertTrue(first.is_public)
        self.assertTrue(second.is_public)
        self.assertFalse(pending.is_public)
        self.assertFalse(withheld.is_public)
        self.assertFalse(breed.is_public)
        self.assertFalse(DogDocument.objects.get(pk=document.pk).is_public)

        first_page = self.client.get(reverse("registry:dog-detail", args=[self.first.slug]))
        second_page = self.client.get(reverse("registry:dog-detail", args=[self.second.slug]))
        self.assertContains(first_page, "DSRA")
        self.assertContains(first_page, "Clear")
        self.assertContains(second_page, "Normal elbows")
        self.assertNotContains(first_page, "Not verified")
        self.assertNotContains(second_page, "Not verified")
        self.assertNotContains(first_page, "100% Cane Corso")
        self.assertNotContains(first_page, "CMR1")
        self.assertNotContains(second_page, "Unreviewed marker")

    def test_existing_published_results_display_without_verification_badges(self):
        HealthRecord.objects.create(
            dog=self.first, test_type="CMR1", result="Clear",
            verification_state=VerificationState.COMMUNITY, is_public=True,
        )
        page = self.client.get(reverse("registry:dog-detail", args=[self.first.slug]))
        self.assertContains(page, "CMR1")
        self.assertContains(page, "Clear")
        self.assertNotContains(page, "Not verified")
        self.assertNotContains(page, "Reviewed results")  # No false lab-verified banner.
