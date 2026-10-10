"""Regression tests for owner-requested profile, ancestry and image corrections."""
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from registry.models import (
    DisputeCase, Dog, DogDocument, DogImage, DogTitle,
    Kennel, ModerationRoleAssignment, Submission,
)
from registry.services import approve_submission


class OwnerFeedbackFixesTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        media_settings = override_settings(
            MEDIA_ROOT=self.temp_media.name, MEDIA_EDGE_BASE_URL="",
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        user = get_user_model()
        self.owner = user.objects.create_superuser(
            username="owner-feedback-owner", email="owner-feedback-owner@example.com",
            password="safe-test-only",
        )
        self.staff = user.objects.create_user(username="owner-feedback-staff")
        self.member = user.objects.create_user(username="owner-feedback-member")
        ModerationRoleAssignment.objects.create(
            user=self.owner, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        self.kennel = Kennel.objects.create(name="Owner Test Kennel", slug="owner-test-kennel")
        self.dog = Dog.objects.create(
            name="Owner Review Dog", slug="owner-review-dog",
            sex=Dog.Sex.MALE, kennel=self.kennel, is_public=True,
        )

    def test_parent_picker_requires_staff_and_returns_exact_identity(self):
        sire = Dog.objects.create(
            name="Common Parent", slug="owner-sire", sex=Dog.Sex.MALE, is_public=False,
        )
        Dog.objects.create(
            name="Common Parent", slug="owner-dam",
            sex=Dog.Sex.FEMALE, is_public=False,
        )
        url = reverse("accounts:dog-parent-suggestions")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url, {"q": "Common", "sex": "male"}).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get(url, {"q": "Common", "sex": "male"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], [str(sire.pk)])
        self.assertEqual(response.json()["results"][0]["is_public"], False)
        self.assertEqual(self.client.get(url, {"q": "C", "sex": "male"}).json(), {"results": []})

    @patch("registry.services.verify_submission", return_value=[])
    def test_title_certificate_stays_private_until_review(self, _verification):
        sub = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, submitted_by=self.member,
            dog=self.dog, kennel=self.kennel,
            payload={
                "title": "Champion award proof",
                "document_type": DogDocument.DocumentType.TITLE_CERTIFICATE,
                "achievement_title": "National Champion",
                "certificate_issuer": "Example Club",
                "certificate_awarded_on": "2025-05-01",
                "is_public": True,
            },
            attachment=SimpleUploadedFile("award.pdf", b"%PDF-1.4 owner-test"),
        )
        url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.assertNotContains(self.client.get(url), "National Champion")
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(sub, self.staff, "Certificate checked")
        title = DogTitle.objects.select_related("certificate_document").get(dog=self.dog)
        self.assertEqual(title.name, "National Champion")
        self.assertEqual(title.issuer, "Example Club")
        self.assertEqual(title.certificate_document.source_submission_id, sub.pk)
        self.assertContains(self.client.get(url), "View reviewed certificate")

    def test_reported_photo_replacement_changes_only_reviewed_image(self):
        previous = DogImage.objects.create(
            dog=self.dog, image=SimpleUploadedFile(
                "previous.jpg", b"original-photo-data", content_type="image/jpeg",
            ), is_primary=True,
        )
        case = DisputeCase.objects.create(
            dog=self.dog, opened_by=self.member,
            reason=DisputeCase.Reason.PHOTO,
            details="The published image belongs to a different dog.",
            target_image=previous,
            attachment=SimpleUploadedFile(
                "new-photo.jpg", b"replacement-photo-data", content_type="image/jpeg",
            ),
        )
        self.client.force_login(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("accounts:review-dispute", args=[case.pk, "replace_photo"]),
                {"resolution_notes": "Verified picture against club records"},
            )
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.status, DisputeCase.Status.RESOLVED)
        self.assertFalse(DogImage.objects.filter(pk=previous.pk).exists())
        replacement = DogImage.objects.get(dog=self.dog, is_primary=True)
        self.assertIn("new-photo", replacement.image.name)
        self.assertContains(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])),
            replacement.image.url,
        )
        # Closed disputes cannot be replayed to delete a later correction.
        self.client.post(
            reverse("accounts:review-dispute", args=[case.pk, "remove_photo"]),
            {"resolution_notes": "Unexpected replay"},
        )
        self.assertTrue(DogImage.objects.filter(pk=replacement.pk).exists())

    def test_photo_case_cannot_be_closed_without_corrective_action(self):
        case = DisputeCase.objects.create(
            dog=self.dog, opened_by=self.member,
            reason=DisputeCase.Reason.PHOTO,
            details="Incorrect photograph",
        )
        self.client.force_login(self.staff)
        self.client.post(
            reverse("accounts:review-dispute", args=[case.pk, "resolve"]),
            {"resolution_notes": "Simply mark done"},
        )
        case.refresh_from_db()
        self.assertEqual(case.status, DisputeCase.Status.OPEN)
