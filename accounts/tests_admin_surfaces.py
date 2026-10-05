from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from registry.data_quality import quick_quality_report
from registry.models import (
    Dog,
    DogSource,
    ModerationRoleAssignment,
    Submission,
    SubmissionRiskLevel,
    SubmissionVerificationStatus,
    VerificationRule,
)
from registry.verification import current_findings, verify_submission


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
        )
        verify_submission(self.submission)

    def test_owner_admin_surfaces_render(self):
        self.client.force_login(self.owner)

        urls = [
            reverse("admin:index"),
            reverse("admin:auth_user_changelist"),
            reverse("admin:registry_submission_changelist"),
            reverse("admin:registry_dog_changelist"),
            reverse("admin:registry_verificationevent_changelist"),
            reverse("admin:registry_mergehistory_changelist"),
            reverse("admin:registry_disputecase_changelist"),
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

    def test_data_health_report_uses_bounded_query_count(self):
        dog = Dog.objects.create(
            name="Health Source Dog",
            slug="health-source-dog",
            is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_type=DogSource.SourceType.WEB,
            title="Health source",
            verified_at=None,
        )

        with CaptureQueriesContext(connection) as captured:
            report = quick_quality_report(sample_limit=2)

        self.assertLessEqual(len(captured), 12)
        self.assertGreaterEqual(report["counts"]["public_dogs"], 1)
        self.assertGreaterEqual(report["counts"]["source_backed_public"], 1)

    def test_data_health_page_caches_repeated_reads(self):
        cache.clear()
        self.client.force_login(self.owner)
        fake_report = {
            "counts": {
                "public_dogs": 1,
                "source_backed_public": 1,
                "verified_source_backed_public": 0,
                "pedigree_linked_public": 0,
                "public_without_sources": 0,
                "community_only_public": 0,
                "unknown_sex_public": 0,
                "sire_sex_conflicts": 0,
                "dam_sex_conflicts": 0,
                "same_parent_conflicts": 0,
                "parent_date_conflicts": 0,
                "pending_submissions": 0,
                "aging_submissions": 0,
                "open_disputes": 0,
            },
            "source_coverage_percent": 100.0,
            "verified_source_coverage_percent": 0.0,
            "pedigree_linkage_percent": 0.0,
            "samples": {},
        }

        with patch("accounts.views.quick_quality_report", return_value=fake_report) as report:
            first = self.client.get(reverse("accounts:data-health"))
            second = self.client.get(reverse("accounts:data-health"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        report.assert_called_once_with(sample_limit=12)

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
        self.assertEqual(response.url, reverse("admin:index"))
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

    def test_invalid_role_user_id_is_rejected_without_500(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:moderation-set-role"),
            {
                "user_id": "not-an-integer",
                "role": ModerationRoleAssignment.Role.REVIEWER,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("accounts:verification-dashboard"),
        )

    def test_invalid_bulk_submission_uuid_is_rejected_without_500(self):
        self.client.force_login(self.owner)
        original_priority = self.submission.priority

        response = self.client.post(
            reverse("accounts:bulk-moderation"),
            {
                "submission_ids": ["not-a-uuid"],
                "action": "priority_urgent",
                "resolution_notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:moderation"))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.priority, original_priority)

    def test_invalid_duplicate_reference_is_safe_and_visible(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("accounts:moderation"),
            {"reference": "not-a-uuid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "duplicate-reference ID is invalid")

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

    def test_malformed_parent_ids_become_findings_instead_of_500(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            payload={
                "name": "Malformed Parent Dog",
                "sex": "unknown",
                "sire_id": "not-a-uuid",
                "dam_id": "also-not-a-uuid",
                "date_of_birth": "2025-01-01",
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
        submission.refresh_from_db()
        self.assertEqual(
            submission.verification_status,
            SubmissionVerificationStatus.REVIEW,
        )
        self.assertEqual(
            current_findings(submission).filter(code="invalid_reference").count(),
            2,
        )

    def test_rule_update_invalidates_pending_without_rechecking_all_in_request(self):
        rule = VerificationRule.objects.create(
            code="invalid_reference",
            title="Malformed canonical reference",
            risk_level=SubmissionRiskLevel.YELLOW,
        )
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.verification_status,
            SubmissionVerificationStatus.PASS,
        )
        self.client.force_login(self.owner)

        with patch("accounts.views.verify_submission") as verify:
            response = self.client.post(
                reverse("accounts:verification-rule-update", args=[rule.pk]),
                {
                    "enabled": "on",
                    "risk_level": SubmissionRiskLevel.RED,
                },
            )

        self.assertEqual(response.status_code, 302)
        verify.assert_not_called()
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.verification_status,
            SubmissionVerificationStatus.UNCHECKED,
        )
        self.assertIsNone(self.submission.verification_checked_at)


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
