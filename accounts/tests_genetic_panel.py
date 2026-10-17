"""Focused public genetic-status and repeat-owner-upload regressions."""
from datetime import date, datetime
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.genetic_health import marker_status_rows
from registry.models import (
    Dog, HealthRecord, Kennel, KennelMembership, ModerationRoleAssignment,
    Submission, VerificationState,
)
from registry.services import approve_submission


class GeneticPanelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="gene-owner", password="testpass123")
        self.outsider = User.objects.create_user(username="gene-outsider", password="testpass123")
        self.reviewer = User.objects.create_user(username="gene-reviewer")
        ModerationRoleAssignment.objects.create(user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER)
        self.kennel = Kennel.objects.create(name="DNA Tests Kennel", slug="dna-tests-kennel", verified_at=timezone.now())
        KennelMembership.objects.create(user=self.owner, kennel=self.kennel, role=KennelMembership.Role.OWNER)
        self.dog = Dog.objects.create(name="DNA Tests Dog", slug="dna-tests-dog", kennel=self.kennel, is_public=True)
        self.url = reverse("accounts:submit-health-record", args=[self.dog.pk])
        self.profile = reverse("registry:dog-detail", args=[self.dog.slug])

    @staticmethod
    def evidence():
        return SimpleUploadedFile("genetics.pdf", b"%PDF-1.4\nDocument\n", content_type="application/pdf")

    def submit_marker(self, marker, status):
        return self.client.post(self.url, {
            "evidence_type": "dna",
            "genetic_marker": marker,
            "genetic_status": status,
            "tested_on": "2026-10-15",
            "attachment": self.evidence(),
        })

    def test_unknown_dog_starts_not_tested_without_fake_clear_or_percentage(self):
        response = self.client.get(self.profile)
        self.assertContains(response, "No available records")
        self.assertNotContains(response, "genetic-screening-status--untested")
        self.assertNotContains(response, "100% Cane Corso")
        self.assertNotContains(response, "genetic-screening-status--clear")

    def test_public_status_only_after_approval_and_members_can_upload_again(self):
        self.client.force_login(self.owner)
        upload = self.submit_marker("DSRA", "Clear")
        self.assertEqual(upload.status_code, 302)
        submission = Submission.objects.get(kind=Submission.Kind.HEALTH)
        self.assertNotContains(self.client.get(self.profile), 'genetic-screening-status--clear')
        approve_submission(submission, self.reviewer)
        page = self.client.get(self.profile)
        self.assertContains(page, 'genetic-screening-status--clear')
        self.assertContains(page, "Upload health / DNA report")
        self.assertContains(self.client.get(reverse("accounts:my-pedigrees")), "Upload health / DNA")
        # A later report for a second marker is allowed with the same canonical dog.
        result = self.submit_marker("NCL1", "Carrier")
        self.assertEqual(result.status_code, 302)
        submission = Submission.objects.filter(kind=Submission.Kind.HEALTH).order_by("-created_at").first()
        approve_submission(submission, self.reviewer)
        self.client.logout()
        page = self.client.get(self.profile)
        self.assertContains(page, 'genetic-screening-status--clear')
        self.assertContains(page, 'genetic-screening-status--carrier')
        self.assertContains(page, "genetic-screening-status--untested", count=1)
        self.client.force_login(self.outsider)
        self.assertEqual(self.submit_marker("CMR1", "Clear").status_code, 403)

    def test_rejects_missing_or_unrecognized_marker_status_without_creating_submission(self):
        self.client.force_login(self.owner)
        for status in ("", "Not tested", "Healthy"):
            response = self.submit_marker("CMR1", status)
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Submission.objects.exists())
        # Normal DNA parentage free-text submissions still work.
        response = self.client.post(self.url, {
            "evidence_type": "dna", "test_type": "DNA parentage",
            "result": "Verified", "attachment": self.evidence(),
        })
        self.assertEqual(response.status_code, 302)
        # Cannot sneak in an ambiguous DSRA result through the legacy free text.
        response = self.client.post(self.url, {
            "evidence_type": "dna", "test_type": "DSRA",
            "result": "Probably clear", "attachment": self.evidence(),
        })
        self.assertEqual(response.status_code, 200)

    def test_latest_reviewed_marker_wins_and_unverified_never_means_clear(self):
        now = timezone.now()
        def record(pk, code, result, state, day):
            return SimpleNamespace(pk=pk, test_type=code, result=result,
                verification_state=state, tested_on=day, created_at=now)
        records = [
            record(1, "DSRA", "Clear", VerificationState.COMMUNITY, date(2026, 10, 16)),
            record(2, "DSRA", "Carrier", VerificationState.HEALTH_VERIFIED, date(2026, 10, 14)),
            record(3, "DSRA", "Clear", VerificationState.HEALTH_VERIFIED, date(2026, 10, 15)),
            record(4, "NCL1", "Affected", VerificationState.HEALTH_VERIFIED, date(2026, 10, 15)),
            record(5, "CMR1", "Not tested", VerificationState.HEALTH_VERIFIED, date(2026, 10, 15)),
        ]
        rows = marker_status_rows(records)
        self.assertEqual([(r["code"], r["status"]) for r in rows],
            [("DSRA", "Clear"), ("NCL1", "Affected"), ("CMR1", "Not tested")])
