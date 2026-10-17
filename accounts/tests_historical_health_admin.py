from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, Kennel,
    KennelMembership, ModerationAudit, ModerationRoleAssignment, VerificationEvent,
)


class HistoricalHealthAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="staff-owner", password="password123", is_superuser=True, is_staff=True)
        self.reviewer = User.objects.create_user(username="staff-reviewer", password="password123")
        ModerationRoleAssignment.objects.create(user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER)
        self.member = User.objects.create_user(username="kennel-member", password="password123")
        self.kennel = Kennel.objects.create(name="Lab Evidence Kennel", slug="lab-evidence-kennel", verified_at=timezone.now())
        KennelMembership.objects.create(user=self.member, kennel=self.kennel, role=KennelMembership.Role.OWNER)
        self.dog = Dog.objects.create(name="Lab Evidence Dog", slug="lab-evidence-dog", kennel=self.kennel, is_public=True)
        self.url = reverse("accounts:health-genetic-dog", args=[self.dog.pk])

    def report(self):
        return SimpleUploadedFile("lab-report.pdf", b"%PDF-1.4\nTest result\n", content_type="application/pdf")

    def test_only_super_admin_can_access_or_write(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_reviewed_health_result_public_but_uploaded_evidence_staff_only(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            "record_type": "health", "test_type": "Hip score", "result": "A",
            "source_reference": "Official hip certificate 5", "attachment": self.report(),
            "review_attestation": "on",
        })
        self.assertEqual(response.status_code, 302)
        record = HealthRecord.objects.get(dog=self.dog)
        self.assertEqual(record.result, "A")
        self.assertTrue(record.evidence_document.staff_review_only)
        self.assertFalse(record.evidence_document.is_public)
        self.assertTrue(VerificationEvent.objects.filter(health_record=record, reviewer=self.owner).exists())
        self.assertTrue(ModerationAudit.objects.filter(dog=self.dog, summary__kind="historical_health_evidence").exists())
        self.client.logout()
        page = self.client.get(reverse("registry:dog-detail", args=[self.dog.slug]))
        self.assertContains(page, "Hip score")
        media = reverse("media-file", kwargs={"path": record.evidence_document.file.name})
        self.assertEqual(self.client.get(media).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(media).status_code, 404)

    def test_historical_breed_dna_never_leaks_without_owner_consent(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            "record_type": "breed", "laboratory": "Embark",
            "cane_corso_percentage": "92.5", "other_breeds": "Boxer: 7.5",
            "source_reference": "Lab report 123", "attachment": self.report(),
            "review_attestation": "on",
        })
        self.assertEqual(response.status_code, 302)
        report = BreedDNAReport.objects.get(health_record__dog=self.dog)
        self.assertFalse(report.consent_public_summary)
        self.assertFalse(report.consent_full_report)
        self.assertTrue(report.evidence_document.staff_review_only)
        self.client.logout()
        page = self.client.get(reverse("registry:dog-detail", args=[self.dog.slug]))
        self.assertNotContains(page, "92.5% Cane Corso")
        self.assertNotContains(page, "Boxer")
        self.assertNotContains(page, "Lab report 123")

    def test_invalid_composition_and_missing_evidence_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            "record_type": "breed", "laboratory": "Embark",
            "cane_corso_percentage": "92.5", "other_breeds": "Boxer: 5",
            "source_reference": "Lab report 123", "attachment": self.report(),
            "review_attestation": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must add up to exactly 100")
        self.assertFalse(HealthRecord.objects.exists())
        response = self.client.post(self.url, {
            "record_type": "health", "test_type": "Hip score", "result": "A",
            "source_reference": "source", "review_attestation": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HealthRecord.objects.exists())

    def test_withdraw_revokes_every_breed_summary_and_report_without_erasing_evidence(self):
        self.client.force_login(self.owner)
        for pct in ("100.00", "98.00"):
            doc = DogDocument.objects.create(
                dog=self.dog, title="Authorized DNA", document_type="dna",
                file=self.report(), is_public=True, submitted_by=self.member,
            )
            result = HealthRecord.objects.create(dog=self.dog, test_type="DNA breed composition", result=pct + "% Cane Corso")
            BreedDNAReport.objects.create(
                health_record=result, evidence_document=doc, provider="Embark",
                cane_corso_percentage=pct,
                composition=[{"breed":"Cane Corso","percentage":pct}],
                consent_public_summary=True, consent_full_report=True,
            )
        withdraw_url = reverse("accounts:health-genetic-withdraw", args=[self.dog.pk])
        self.assertEqual(self.client.get(withdraw_url).status_code, 405)
        self.assertEqual(self.client.post(withdraw_url, {}).status_code, 302)
        self.assertEqual(BreedDNAReport.objects.filter(consent_public_summary=True).count(), 2)
        self.assertEqual(self.client.post(withdraw_url, {"confirmation":"hide_all"}).status_code, 302)
        self.assertEqual(BreedDNAReport.objects.filter(consent_public_summary=True).count(), 0)
        self.assertEqual(BreedDNAReport.objects.filter(consent_full_report=True).count(), 0)
        self.assertFalse(DogDocument.objects.filter(is_public=True).exists())
        self.assertEqual(HealthRecord.objects.count(), 2)
        self.client.logout()
        page = self.client.get(reverse("registry:dog-detail", args=[self.dog.slug]))
        self.assertNotContains(page, "DNA tested · Embark")
