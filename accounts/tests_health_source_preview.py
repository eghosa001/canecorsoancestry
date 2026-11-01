"""Accepted member health uploads must be accessible to reviewers but not visitors."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    Dog, DogDocument, HealthRecord, Kennel, KennelMembership,
    ModerationRoleAssignment, Submission, VerificationState,
)
from registry.services import approve_submission


class HealthSourcePreviewTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.member = users.objects.create_user(username="preview-member")
        self.reviewer = users.objects.create_user(username="preview-reviewer")
        self.outsider = users.objects.create_user(username="preview-outsider")
        ModerationRoleAssignment.objects.create(
            user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER
        )
        kennel = Kennel.objects.create(
            name="Preview Kennel", slug="preview-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=self.member, kennel=kennel, role=KennelMembership.Role.OWNER
        )
        self.dog = Dog.objects.create(
            name="Preview Test Dog", slug="preview-test-dog",
            kennel=kennel, is_public=True,
        )
        self.other_dog = Dog.objects.create(
            name="Another Preview Dog", slug="another-preview-dog",
        )

    def approve_upload(self):
        self.client.force_login(self.member)
        response = self.client.post(
            reverse("accounts:submit-health-record", args=[self.dog.pk]),
            {
                "evidence_type": "health",
                "test_type": "Hip scores", "result": "A",
                "attachment": SimpleUploadedFile(
                    "hip-evidence.pdf", b"%PDF-1.4 test original",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get(
            dog=self.dog, kind=Submission.Kind.HEALTH,
        )
        submission.payload["laboratory"] = "Canine Diagnostic Laboratory"
        submission.save(update_fields=["payload"])
        self.client.force_login(self.reviewer)
        approve_submission(submission, self.reviewer)
        return submission

    def test_original_member_pdf_can_be_read_after_approval(self):
        submission = self.approve_upload()
        url = reverse(
            "accounts:preview-health-submission",
            args=[self.dog.pk, submission.pk],
        )
        health = self.client.get(reverse(
            "accounts:reviewed-dog-health", args=[self.dog.pk],
        ))
        self.assertContains(health, url)
        self.assertContains(health, "Canine Diagnostic Laboratory")
        self.assertContains(health, "Open selected original PDF / image")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        self.assertIn("no-store", response["Cache-Control"])
        response.close()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.reviewer)
        other = reverse(
            "accounts:preview-health-submission",
            args=[self.other_dog.pk, submission.pk],
        )
        self.assertEqual(self.client.get(other).status_code, 404)

    def test_individual_editor_can_recover_original_file(self):
        submission = self.approve_upload()
        doc = DogDocument.objects.get(source_submission=submission)
        record = HealthRecord.objects.get(
            dog=self.dog, test_type="Hip scores"
        )
        self.assertEqual(record.evidence_document_id, doc.pk)
        preview = reverse(
            "accounts:preview-health-submission",
            args=[self.dog.pk, submission.pk],
        )
        editor = reverse(
            "accounts:edit-reviewed-health-result",
            args=[self.dog.pk, record.pk],
        )
        self.assertContains(self.client.get(editor), preview)
        record.evidence_document = None
        record.save(update_fields=["evidence_document"])
        self.assertContains(self.client.get(editor), preview)
        marker = HealthRecord.objects.create(
            dog=self.dog, test_type="CMR1", result="Clear",
            verification_state=VerificationState.HEALTH_VERIFIED,
            notes="Moderator reviewed private lab evidence for submission "
            + str(submission.pk),
        )
        marker_editor = reverse(
            "accounts:edit-reviewed-health-result",
            args=[self.dog.pk, marker.pk],
        )
        self.assertContains(self.client.get(marker_editor), preview)


    def test_two_results_from_same_report_can_both_open_original(self):
        accepted = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT,
            status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.member,
            payload={"document_type": DogDocument.DocumentType.HEALTH},
        )
        document = DogDocument.objects.create(
            dog=self.dog, title="Two-marker diagnostic report",
            document_type=DogDocument.DocumentType.HEALTH,
            file=SimpleUploadedFile(
                "both-markers.pdf", b"%PDF-1.4 two laboratory markers",
                content_type="application/pdf",
            ),
            source_submission=accepted,
            submitted_by=self.member,
        )
        self.client.force_login(self.reviewer)
        save = reverse("accounts:save-structured-health", args=[self.dog.pk])
        reply = self.client.post(save, {
            "source_document": document.pk,
            "cmr1": "Clear",
            "dsra": "Carrier",
            "reviewed": "on",
        })
        self.assertRedirects(
            reply, reverse("accounts:reviewed-dog-health", args=[self.dog.pk]),
        )
        results = HealthRecord.objects.filter(
            dog=self.dog, test_type__in=["CMR1", "DSRA"]
        )
        self.assertEqual(results.count(), 2)
        preview = reverse(
            "accounts:preview-health-document", args=[self.dog.pk, document.pk],
        )
        for result in results:
            with self.subTest(condition=result.test_type):
                edit = reverse(
                    "accounts:edit-reviewed-health-result",
                    args=[self.dog.pk, result.pk],
                )
                self.assertContains(self.client.get(edit), preview)

    def test_approved_document_preview_and_pending_source_exclusion(self):
        accepted = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT,
            status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.member,
            payload={"document_type": DogDocument.DocumentType.HEALTH},
        )
        document = DogDocument.objects.create(
            dog=self.dog, title="Accepted diagnostic report",
            document_type=DogDocument.DocumentType.HEALTH,
            file=SimpleUploadedFile(
                "report.pdf", b"%PDF-1.4 lab report",
                content_type="application/pdf",
            ),
            source_submission=accepted,
            submitted_by=self.member,
        )
        pending = Submission.objects.create(
            kind=Submission.Kind.HEALTH,
            status=Submission.Status.PENDING,
            dog=self.dog, submitted_by=self.member,
            attachment="health/unapproved-report.pdf",
        )
        self.client.force_login(self.reviewer)
        doc_url = reverse(
            "accounts:preview-health-document",
            args=[self.dog.pk, document.pk],
        )
        page = self.client.get(reverse(
            "accounts:reviewed-dog-health", args=[self.dog.pk],
        ))
        self.assertContains(page, doc_url)
        self.assertNotContains(page, "health/unapproved-report.pdf")
        response = self.client.get(doc_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        response.close()
        pending_url = reverse(
            "accounts:preview-health-submission",
            args=[self.dog.pk, pending.pk],
        )
        self.assertEqual(self.client.get(pending_url).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(doc_url).status_code, 403)
