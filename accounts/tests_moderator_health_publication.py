"""Focused moderator transcription, visibility, role and evidence privacy tests."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, Kennel, KennelMembership,
    ModerationRoleAssignment, Submission, VerificationState,
)
from registry.services import approve_submission


class ModeratorLabResultTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="health-owner", password="abc123xyz")
        self.moderator = User.objects.create_user(username="health-moderator", password="abc123xyz")
        self.unauthorized = User.objects.create_user(username="unrelated-member", password="abc123xyz")
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER
        )
        self.kennel = Kennel.objects.create(
            name="Moderation health kennel", slug="moderation-health-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=self.owner, kennel=self.kennel, role=KennelMembership.Role.OWNER
        )
        self.dog = Dog.objects.create(
            name="Moderator Lab Dog", slug="moderator-lab-dog",
            kennel=self.kennel, is_public=True,
        )
        self.submit_url = reverse("accounts:submit-health-record", args=[self.dog.pk])
        self.public_url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.health_url = reverse("accounts:reviewed-dog-health", args=[self.dog.pk])

    def upload(self, kind="health"):
        self.client.force_login(self.owner)
        response = self.client.post(self.submit_url, {
            "evidence_type": kind, "test_type": "Hip scores",
            "result": "A", "attachment": SimpleUploadedFile(
                "health-scan.pdf", b"%PDF-1.4\\n% test evidence\\n", content_type="application/pdf"
            ),
        })
        self.assertEqual(response.status_code, 302)
        return Submission.objects.get(kind=Submission.Kind.HEALTH)

    def test_no_report_means_no_available_records(self):
        page = self.client.get(self.public_url)
        self.assertContains(page, "No available records")
        self.assertNotContains(page, "genetic-screening-status--clear")

    def test_moderator_transcribes_one_image_into_three_separate_results(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        edit_url = reverse("accounts:transcribe-health-submission", args=[submission.pk])
        response = self.client.post(edit_url, {
            "publish_primary": "", "reviewed": "on",
            "status_DSRA": "Clear", "publish_DSRA": "on",
            "status_NCL1": "Carrier", "publish_NCL1": "on",
            "status_CMR1": "Affected",
        })
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertEqual(submission.payload["reviewed_markers"]["NCL1"]["status"], "Carrier")
        self.assertNotContains(self.client.get(self.public_url), "genetic-screening-status--carrier")
        approve_submission(submission, self.moderator)
        records = HealthRecord.objects.filter(dog=self.dog)
        self.assertEqual(records.count(), 4)
        self.assertFalse(records.get(test_type="Hip scores").is_public)
        self.assertFalse(records.get(test_type="CMR1").is_public)
        doc = DogDocument.objects.get(source_submission=submission)
        self.assertFalse(doc.is_public)
        self.client.logout()
        public = self.client.get(self.public_url)
        self.assertContains(public, "genetic-screening-status--clear")
        self.assertContains(public, "genetic-screening-status--carrier")
        self.assertContains(public, "genetic-screening-status--untested")
        self.assertNotContains(public, "health-scan.jpg")

    def test_staff_can_hide_and_restore_only_reviewed_summary(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        record = HealthRecord.objects.get(dog=self.dog)
        action = reverse("accounts:toggle-health-result", args=[self.dog.pk, record.pk])
        self.assertEqual(self.client.post(action, {"visibility": "hide"}).status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get(self.public_url), "No available records")
        self.client.force_login(self.moderator)
        self.assertEqual(self.client.post(action, {"visibility": "show"}).status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get(self.public_url), "Hip scores")
        self.client.force_login(self.unauthorized)
        self.assertEqual(self.client.get(self.health_url).status_code, 403)
        self.assertEqual(self.client.post(action, {"visibility": "hide"}).status_code, 403)

    def test_never_publish_original_health_image(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        doc = DogDocument.objects.get(source_submission=submission)
        # Even if a legacy doc flag is mistakenly set True, the private-media
        # access gate must prevent external access.
        doc.is_public = True
        doc.save(update_fields=["is_public"])
        from core.media_views import _can_read_media
        self.assertEqual(_can_read_media(self.unauthorized, doc.file.name), (False, False))
        self.client.logout()
        self.assertNotContains(self.client.get(self.public_url), "View owner-authorized DNA report")

    def test_staff_cannot_publish_breed_report_without_owner_consent(self):
        report = HealthRecord.objects.create(
            dog=self.dog, test_type="DNA breed composition", result="100% Cane Corso",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        evidence = DogDocument.objects.create(
            dog=self.dog, title="private lab", document_type="dna",
            file="private/documents/genetic.pdf", is_public=False,
            staff_review_only=True, submitted_by=self.moderator,
        )
        BreedDNAReport.objects.create(
            health_record=report, evidence_document=evidence,
            provider="Embark", cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=False,
        )
        self.client.force_login(self.moderator)
        action = reverse("accounts:toggle-health-result", args=[self.dog.pk, report.pk])
        self.assertEqual(self.client.post(action, {"visibility": "show"}).status_code, 302)
        report.refresh_from_db()
        self.assertFalse(report.is_public)
        self.client.logout()
        self.assertNotContains(self.client.get(self.public_url), "100% Cane Corso")

    def test_incomplete_lab_transcription_is_rejected(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        url = reverse("accounts:transcribe-health-submission", args=[submission.pk])
        self.client.post(url, {"status_CMR1": "", "publish_CMR1": "on", "reviewed": "on"})
        submission.refresh_from_db()
        self.assertNotIn("reviewed_markers", submission.payload)
