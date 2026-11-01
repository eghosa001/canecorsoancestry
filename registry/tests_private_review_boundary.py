"""Private review workflow must never leak onto public or member dog pages."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.media_views import _can_read_media
from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, Kennel,
    KennelMembership, ModerationRoleAssignment, Submission, VerificationState,
)


class PrivateReviewBoundaryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(username="member-review-privacy")
        self.staff = User.objects.create_user(username="staff-review-privacy")
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.kennel = Kennel.objects.create(
            name="Private review kennel", slug="private-review-kennel",
        )
        self.dog = Dog.objects.create(
            name="Private review dog", slug="private-review-dog",
            kennel=self.kennel, is_public=True,
        )
        KennelMembership.objects.create(
            user=self.member, kennel=self.kennel, role=KennelMembership.Role.OWNER,
        )
        self.profile_url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.staff_url = reverse("accounts:reviewed-dog-health", args=[self.dog.pk])

    def test_unpublished_verified_and_stale_unverified_data_are_staff_only(self):
        HealthRecord.objects.create(
            dog=self.dog, test_type="CMR1", result="Affected",
            verification_state=VerificationState.HEALTH_VERIFIED,
            is_public=False, notes="INTERNAL REVIEW NOTE: keep confidential",
        )
        HealthRecord.objects.create(
            dog=self.dog, test_type="DSRA", result="Carrier",
            verification_state=VerificationState.COMMUNITY,
            is_public=True, notes="INTERNAL UNVERIFIED SOURCE",
        )
        for viewer in (None, self.member):
            if viewer is not None:
                self.client.force_login(viewer)
            else:
                self.client.logout()
            page = self.client.get(self.profile_url)
            self.assertEqual(page.status_code, 200)
            for forbidden in (
                "CMR1", "DSRA", "Affected", "Carrier",
                "INTERNAL REVIEW NOTE", "INTERNAL UNVERIFIED SOURCE",
                "checked privately", "Report reviewed", "privately reviewed",
                "Verified results", "Health/DNA verified",
            ):
                self.assertNotContains(page, forbidden)
            self.assertContains(page, "No available records")
            self.assertEqual(self.client.get(self.staff_url).status_code, 403)
        self.client.force_login(self.staff)
        page = self.client.get(self.staff_url)
        self.assertContains(page, "CMR1")
        self.assertContains(page, "Held privately")
        self.assertContains(page, "DSRA")

    def test_publication_displays_result_not_private_review_notes(self):
        record = HealthRecord.objects.create(
            dog=self.dog, test_type="CMR1", result="Clear",
            verification_state=VerificationState.HEALTH_VERIFIED,
            is_public=False, notes="STAFF CONFIDENTIAL DECISION",
        )
        toggle = reverse(
            "accounts:toggle-health-result", args=[self.dog.pk, record.pk],
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(toggle, {"visibility": "show"}).status_code, 302,
        )
        record.refresh_from_db()
        self.assertTrue(record.is_public)
        for viewer in (None, self.member):
            if viewer is None:
                self.client.logout()
            else:
                self.client.force_login(viewer)
            page = self.client.get(self.profile_url)
            self.assertContains(page, "CMR1")
            self.assertContains(page, "Clear")
            self.assertNotContains(page, "STAFF CONFIDENTIAL DECISION")
            self.assertNotContains(page, "Verified results")
            self.assertNotContains(page, "Report reviewed")
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(toggle, {"visibility": "hide"}).status_code, 302,
        )
        self.client.logout()
        self.assertNotContains(self.client.get(self.profile_url), "CMR1")

    def test_private_dna_certificate_never_listed_even_with_stale_public_flag(self):
        source = DogDocument.objects.create(
            dog=self.dog, title="PRIVATE ORIGINAL DNA CERTIFICATE",
            document_type=DogDocument.DocumentType.DNA,
            file="private/documents/internal-source-lab-report.pdf",
            is_public=True, submitted_by=self.member,
        )
        health = HealthRecord.objects.create(
            dog=self.dog, test_type="DNA breed composition",
            result="100% Cane Corso", is_public=True,
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        BreedDNAReport.objects.create(
            health_record=health, evidence_document=source,
            provider="Embark", cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=False,
        )
        for viewer in (None, self.member):
            if viewer is None:
                self.client.logout()
            else:
                self.client.force_login(viewer)
            page = self.client.get(self.profile_url)
            self.assertNotContains(page, "PRIVATE ORIGINAL DNA CERTIFICATE")
            self.assertNotContains(page, "internal-source-lab-report.pdf")
            self.assertNotContains(page, 'class="breed-dna-score">100')
            self.assertEqual(
                _can_read_media(self.client.session and self.member if viewer else
                                get_user_model()(), source.file.name)[0], False,
            )
        self.assertEqual(_can_read_media(self.staff, source.file.name)[0], True)

    def test_member_submissions_do_not_expose_internal_review_outcomes(self):
        Submission.objects.create(
            dog=self.dog, submitted_by=self.member, kind=Submission.Kind.HEALTH,
            status=Submission.Status.APPROVED,
            notes="PRIVATE MEMBER NOTES", resolution_notes="CONFIDENTIAL STAFF DECISION",
            payload={"test_type": "CMR1", "result": "Clear"},
        )
        self.client.force_login(self.member)
        page = self.client.get(reverse("accounts:submissions"))
        self.assertContains(page, "Report received")
        self.assertNotContains(page, "CONFIDENTIAL STAFF DECISION")
        self.assertNotContains(page, "Approved")
        health_form = self.client.get(
            reverse("accounts:submit-health-record", args=[self.dog.pk]),
        )
        self.assertContains(health_form, "Report received")
        self.assertNotContains(health_form, "Approved")
