"""Moderator yellow-flag governance and fast canonical dog searches."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from registry.models import (
    Dog, DogAlias, DogRegistration, Kennel, ModerationRoleAssignment,
    Submission, SubmissionRiskLevel, SubmissionVerificationStatus,
    VerificationFinding,
)
from registry.services import moderation_dog_ids, moderation_dog_search


class ModeratorYellowApprovalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.moderator = User.objects.create_user(username="fast-moderator", password="review-pass")
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.member = User.objects.create_user(username="fast-member")
        self.kennel = Kennel.objects.create(name="Fast Kennel", slug="fast-kennel")
        self.client.force_login(self.moderator)

    def submission(self, *, risk):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG, submitted_by=self.member, kennel=self.kennel,
            payload={"name": "Staff Reviewed Puppy", "sex": Dog.Sex.MALE},
            status=Submission.Status.PENDING,
            risk_level=risk,
            verification_status=SubmissionVerificationStatus.REVIEW,
            requires_second_review=(risk == SubmissionRiskLevel.RED),
        )
        VerificationFinding.objects.create(
            submission=submission, code="duplicate_submission" if risk == SubmissionRiskLevel.YELLOW else "duplicate_identity",
            risk_level=risk, message="Reviewer must explain this automated finding.",
            is_current=True,
        )
        return submission

    def test_yellow_warning_has_documented_approval_form_for_normal_moderator(self):
        sub = self.submission(risk=SubmissionRiskLevel.YELLOW)
        res = self.client.get(reverse("accounts:moderation-submission", args=[sub.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            res.context["can_approve_yellow"],
            f"yellow_enabled={res.context.get('can_approve_yellow')} findings={[(f.code, f.risk_level) for f in res.context['blocking_findings']]} "
            f"high_risk={res.context['has_critical_warning']} reviewer={res.context['reviewer_role']}",
        )
        self.assertContains(res, "Approve yellow warning")
        self.assertContains(res, "Red/high-risk findings still require Senior Moderator")

    def test_normal_moderator_can_approve_yellow_with_reason_and_audit(self):
        sub = self.submission(risk=SubmissionRiskLevel.YELLOW)
        with patch("registry.services.verify_submission", side_effect=lambda obj, audit=False: list(obj.verification_findings.filter(is_current=True))):
            response = self.client.post(
                reverse("accounts:review-submission", args=[sub.pk, "override"]),
                {"resolution_notes": "Compared pedigree documents; duplicate pending form is a separate verified puppy."},
            )
        self.assertEqual(response.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.APPROVED)
        self.assertTrue(sub.dog.is_public)
        self.assertEqual(sub.reviewed_by, self.moderator)
        self.assertEqual(sub.resolution_notes, "Compared pedigree documents; duplicate pending form is a separate verified puppy.")

    def test_normal_moderator_cannot_approve_yellow_without_explanation(self):
        sub = self.submission(risk=SubmissionRiskLevel.YELLOW)
        res = self.client.post(
            reverse("accounts:review-submission", args=[sub.pk, "override"]),
            {"resolution_notes": ""},
        )
        self.assertEqual(res.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.PENDING)

    def test_red_warning_still_forbidden_to_normal_moderator(self):
        sub = self.submission(risk=SubmissionRiskLevel.RED)
        res = self.client.get(reverse("accounts:moderation-submission", args=[sub.pk]))
        self.assertNotContains(res, "Approve yellow warning")
        self.assertContains(res, "only a Senior Moderator or Super Admin")
        with patch("registry.services.verify_submission", side_effect=lambda obj, audit=False: list(obj.verification_findings.filter(is_current=True))):
            self.client.post(
                reverse("accounts:review-submission", args=[sub.pk, "override"]),
                {"resolution_notes": "Try unapproved red-risk override."},
            )
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.PENDING)

    def test_queue_search_finds_pending_dogs_by_payload_name(self):
        sub = self.submission(risk=SubmissionRiskLevel.YELLOW)
        res = self.client.get(reverse("accounts:moderation"), {"q": "Staff Reviewed Puppy"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, str(sub.pk))


class ModeratorDogSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.moderator = User.objects.create_user(username="lookup-moderator")
        ModerationRoleAssignment.objects.create(user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER)
        self.dog = Dog.objects.create(name="Legend Of Delta", slug="legend-of-delta", is_public=True)
        self.private = Dog.objects.create(name="Private Legend", slug="private-legend", is_public=False)
        DogAlias.objects.create(dog=self.dog, name="Delta Champion")
        DogRegistration.objects.create(dog=self.private, number="FCI-LOOKUP-991")
        self.client.force_login(self.moderator)

    def test_indexed_exact_prefix_alias_registration_and_uuid(self):
        self.assertEqual(moderation_dog_ids("Legend Of Delta")[0], self.dog.pk)
        self.assertIn(self.dog.pk, moderation_dog_ids("Legend Of"))
        self.assertIn(self.dog.pk, moderation_dog_ids("Delta Champion"))
        self.assertIn(self.private.pk, moderation_dog_ids("FCI-LOOKUP-991"))
        self.assertEqual(moderation_dog_ids(str(self.private.pk)), [self.private.pk])

    def test_prefix_and_uuid_search_stop_after_one_database_lookup(self):
        with CaptureQueriesContext(connection) as prefix_queries:
            prefix_results = moderation_dog_ids("Legend Of", limit=12)
        self.assertEqual(prefix_results, [self.dog.pk])
        self.assertEqual(len(prefix_queries), 1, "Prefix search must not execute unrelated alias/fuzzy queries")

        with CaptureQueriesContext(connection) as uuid_queries:
            uuid_results = moderation_dog_ids(str(self.dog.pk), limit=12)
        self.assertEqual(uuid_results, [self.dog.pk])
        self.assertEqual(len(uuid_queries), 1, "UUID lookups should return immediately")

    def test_moderation_search_includes_private_dogs_and_bounded_results(self):
        matches = moderation_dog_search("Private Legend", limit=5)
        self.assertEqual(matches[0], self.private)
        self.assertLessEqual(len(matches), 5)
        self.assertEqual(moderation_dog_search(""), [])

    def test_editor_search_is_fast_and_does_not_load_revision_history(self):
        res = self.client.get(reverse("accounts:dog-edit-list"), {"q": "Legend Of"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Legend Of Delta")
        self.assertContains(res, "Revision history is deferred")
        self.assertFalse(res.context["revisions"])
        self.assertEqual(res.context["dogs"][0].pk, self.dog.pk)

    def test_editor_can_explicitly_request_revision_history(self):
        res = self.client.get(reverse("accounts:dog-edit-list"), {"q": "Legend Of", "history": "1"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context["history_deferred"])
