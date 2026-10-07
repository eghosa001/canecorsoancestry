from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    Dog,
    DogDocument,
    HealthRecord,
    Kennel,
    KennelMembership,
    Submission,
    VerificationEvent,
    VerificationState,
)
from registry.services import approve_submission

from .models import Profile


class MemberProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profile-kennel",
            email="profile@example.com",
            password="test-pass-123",
        )
        Profile.objects.create(user=self.user, display_name="Profile Kennel")

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)

    def test_member_can_update_profile_without_changing_kennel_identity(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {"country": "Nigeria", "bio": "Cane Corso breeder profile."},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.country, "Nigeria")
        self.assertEqual(profile.bio, "Cane Corso breeder profile.")
        self.assertEqual(profile.display_name, "Profile Kennel")


class HealthRecordSubmissionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="health-owner",
            password="test-pass-123",
        )
        self.outsider = get_user_model().objects.create_user(
            username="health-outsider",
            password="test-pass-123",
        )
        self.reviewer = get_user_model().objects.create_user(
            username="health-reviewer",
            is_staff=True,
        )
        self.kennel = Kennel.objects.create(
            name="Health Kennel",
            slug="health-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=self.owner,
            kennel=self.kennel,
            role=KennelMembership.Role.OWNER,
        )
        self.dog = Dog.objects.create(
            name="Health Dog",
            slug="health-dog",
            kennel=self.kennel,
            is_public=True,
        )

    @staticmethod
    def evidence():
        return SimpleUploadedFile(
            "hip-result.pdf",
            b"%PDF-1.4\n% test evidence\n",
            content_type="application/pdf",
        )

    def test_unrelated_member_cannot_submit_health_record(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("accounts:submit-health-record", args=[self.dog.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_health_record_stays_pending_until_admin_approval(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:submit-health-record", args=[self.dog.pk]),
            {
                "evidence_type": "health",
                "test_type": "Hip score",
                "result": "A",
                "tested_on": "2026-09-20",
                "attachment": self.evidence(),
                "notes": "Official result supplied.",
            },
        )

        self.assertRedirects(response, reverse("accounts:submissions"))
        submission = Submission.objects.get(
            kind=Submission.Kind.HEALTH,
            submitted_by=self.owner,
            dog=self.dog,
        )
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertFalse(HealthRecord.objects.filter(dog=self.dog).exists())

        approve_submission(submission, self.reviewer, "Evidence checked.")

        record = HealthRecord.objects.get(dog=self.dog, test_type="Hip score")
        self.assertEqual(record.result, "A")
        self.assertEqual(record.verification_state, VerificationState.HEALTH_VERIFIED)
        document = DogDocument.objects.get(source_submission=submission)
        self.assertEqual(document.document_type, DogDocument.DocumentType.HEALTH)
        self.assertFalse(document.is_public)
        self.assertTrue(
            VerificationEvent.objects.filter(
                dog=self.dog,
                health_record=record,
                reviewer=self.reviewer,
                state=VerificationState.HEALTH_VERIFIED,
            ).exists()
        )

    def test_dna_submission_creates_private_dna_evidence_after_approval(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("accounts:submit-health-record", args=[self.dog.pk]),
            {
                "evidence_type": "dna",
                "test_type": "DNA parentage",
                "result": "Verified",
                "attachment": self.evidence(),
            },
        )
        submission = Submission.objects.get(kind=Submission.Kind.HEALTH)

        approve_submission(submission, self.reviewer)

        document = DogDocument.objects.get(source_submission=submission)
        self.assertEqual(document.document_type, DogDocument.DocumentType.DNA)
        self.assertFalse(document.is_public)
