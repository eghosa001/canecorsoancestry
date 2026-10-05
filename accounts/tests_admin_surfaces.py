from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import (
    ModerationRoleAssignment,
    Submission,
    SubmissionVerificationStatus,
)


class AdminSurfaceSmokeTests(TestCase):
    password = "Admin-pass-123"

    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            username="owner-admin",
            email="owner@example.com",
            password=self.password,
        )
        ModerationRoleAssignment.objects.create(
            user=self.owner,
            role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.owner,
        )
        self.member = get_user_model().objects.create_user(
            username="member-one",
            email="member@example.com",
            password="Member-pass-123",
        )
        self.submission = Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=self.member,
            payload={"name": "Smoke Kennel", "slug": "smoke-kennel"},
            verification_status=SubmissionVerificationStatus.PASS,
        )

    def test_owner_admin_surfaces_render(self):
        self.client.force_login(self.owner)

        urls = [
            reverse("admin:index"),
            reverse("accounts:moderation"),
            reverse("accounts:verification-dashboard"),
            reverse("accounts:moderation-audit"),
            reverse("accounts:data-health"),
            reverse(
                "accounts:moderation-submission",
                args=[self.submission.pk],
            ),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_logged_out_moderation_uses_member_login(self):
        response = self.client.get(reverse("accounts:moderation"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response["Location"].startswith(
                f"{settings.LOGIN_URL}?next="
            )
        )

    def test_django_admin_login_accepts_email(self):
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.owner.email,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.owner.pk,
        )

    def test_revoking_moderation_role_revokes_staff_access(self):
        reviewer = get_user_model().objects.create_user(
            username="reviewer-one",
            email="reviewer@example.com",
            password="Reviewer-pass-123",
            is_staff=True,
        )
        ModerationRoleAssignment.objects.create(
            user=reviewer,
            role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:moderation-set-role"),
            {
                "user_id": reviewer.pk,
                "role": ModerationRoleAssignment.Role.NONE,
            },
        )

        self.assertEqual(response.status_code, 302)
        reviewer.refresh_from_db()
        self.assertFalse(reviewer.is_staff)
        self.assertEqual(
            reviewer.ancestry_moderation_role.role,
            ModerationRoleAssignment.Role.NONE,
        )

    def test_invalid_duplicate_reference_is_safe(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("accounts:moderation"),
            {"reference": "not-a-uuid"},
        )

        self.assertEqual(response.status_code, 200)

    def test_queue_get_does_not_run_verification_writes(self):
        legacy = Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=self.member,
            payload={"name": "Legacy Kennel", "slug": "legacy-kennel"},
        )
        self.client.force_login(self.owner)

        with patch("accounts.views.verify_submission") as verify:
            response = self.client.get(reverse("accounts:moderation"))

        self.assertEqual(response.status_code, 200)
        verify.assert_not_called()
        legacy.refresh_from_db()
        self.assertEqual(
            legacy.verification_status,
            SubmissionVerificationStatus.UNCHECKED,
        )

    def test_duplicate_scan_is_on_demand(self):
        self.client.force_login(self.owner)

        with patch("accounts.views.duplicate_candidates", return_value=[]) as scan:
            response = self.client.get(reverse("accounts:moderation"))
            self.assertEqual(response.status_code, 200)
            scan.assert_not_called()

            response = self.client.get(
                reverse("accounts:moderation"),
                {"duplicate_scan": "1"},
            )
            self.assertEqual(response.status_code, 200)
            scan.assert_called_once_with()

    def test_malformed_parent_ids_do_not_crash_review(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            payload={
                "name": "Malformed Parent Dog",
                "sex": "unknown",
                "sire_id": "not-a-uuid",
                "dam_id": "also-not-a-uuid",
            },
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "accounts:moderation-submission",
                args=[submission.pk],
            )
        )

        self.assertEqual(response.status_code, 200)


class SubmissionVerificationTimingTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(
            username="kennel-member",
            email="kennel-member@example.com",
            password="Member-pass-123",
        )
        self.client.force_login(self.member)

    def test_new_kennel_submission_is_verified_before_queue(self):
        response = self.client.post(
            reverse("accounts:submit-kennel"),
            {
                "name": "Immediate Verification Kennel",
                "country": "Nigeria",
                "city": "Benin City",
                "website": "",
                "description": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=self.member,
        )
        self.assertNotEqual(
            submission.verification_status,
            SubmissionVerificationStatus.UNCHECKED,
        )
