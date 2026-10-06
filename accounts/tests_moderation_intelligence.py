from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import (
    DisputeCase,
    Dog,
    Kennel,
    KennelMembership,
    Litter,
    ModerationAudit,
    Submission,
)
from registry.services import (
    approve_submission,
    duplicate_matches,
    moderation_dog_search,
    submission_diff,
)


class ReviewDiffTests(TestCase):
    def test_correction_diff_shows_canonical_and_proposed_values(self):
        user = get_user_model().objects.create_user(username="diff-user")
        dog = Dog.objects.create(
            name="Original Dog",
            slug="original-dog",
            colour="Black",
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.CORRECTION,
            submitted_by=user,
            dog=dog,
            payload={"name": "Updated Dog", "colour": "Brindle"},
        )

        changes = submission_diff(submission)
        by_field = {item["field"]: item for item in changes}

        self.assertEqual(by_field["Name"]["before"], "Original Dog")
        self.assertEqual(by_field["Name"]["after"], "Updated Dog")
        self.assertEqual(by_field["Colour"]["before"], "Black")
        self.assertEqual(by_field["Colour"]["after"], "Brindle")


class DuplicateIntelligenceTests(TestCase):
    def test_ranked_duplicate_match_uses_name_and_pedigree_evidence(self):
        sire = Dog.objects.create(name="Shared Sire", slug="dup-shared-sire")
        dam = Dog.objects.create(name="Shared Dam", slug="dup-shared-dam")
        reference = Dog.objects.create(
            name="Karma Custodi Nos",
            slug="dup-reference",
            sire=sire,
            dam=dam,
        )
        candidate = Dog.objects.create(
            name="Karma Custody Nos",
            slug="dup-candidate",
            sire=sire,
            dam=dam,
        )
        Dog.objects.create(name="Completely Different", slug="dup-other")

        matches = duplicate_matches(reference)

        self.assertEqual(matches[0]["candidate"], candidate)
        self.assertGreaterEqual(matches[0]["score"], 60)
        self.assertIn("Same sire", matches[0]["reasons"])
        self.assertIn("Same dam", matches[0]["reasons"])

    def test_moderator_dog_search_falls_back_to_fuzzy_matching(self):
        dog = Dog.objects.create(name="Karma Custodi Nos", slug="fuzzy-karma")

        results = moderation_dog_search("Karma Custdy")

        self.assertIn(dog, results)


class AuditTrailTests(TestCase):
    def test_approval_creates_audit_event_with_review_diff(self):
        submitter = get_user_model().objects.create_user(username="audit-member")
        reviewer = get_user_model().objects.create_user(
            username="audit-reviewer", is_staff=True
        )
        kennel = Kennel.objects.create(name="Audit Kennel", slug="audit-kennel")
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=submitter,
            kennel=kennel,
            payload={"name": "Audit Dog", "sex": Dog.Sex.UNKNOWN},
        )

        approve_submission(submission, reviewer, "Evidence checked.")

        event = ModerationAudit.objects.get(
            action=ModerationAudit.Action.SUBMISSION_APPROVED
        )
        self.assertEqual(event.actor, reviewer)
        self.assertEqual(event.submission_id, submission.pk)
        self.assertEqual(event.note, "Evidence checked.")
        self.assertTrue(event.summary["changes"])


class BulkModerationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="bulk-reviewer",
            password="test-pass-123",
            is_staff=True,
        )
        submitter = get_user_model().objects.create_user(username="bulk-member")
        self.first = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=submitter,
            payload={"name": "First"},
        )
        self.second = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=submitter,
            payload={"name": "Second"},
        )
        self.client.force_login(self.staff)

    def test_bulk_priority_update_is_safe_and_audited(self):
        response = self.client.post(
            reverse("accounts:bulk-moderation"),
            {
                "submission_ids": [str(self.first.pk), str(self.second.pk)],
                "action": "priority_urgent",
                "resolution_notes": "Escalate pedigree risk.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.priority, Submission.Priority.URGENT)
        self.assertEqual(self.second.priority, Submission.Priority.URGENT)
        self.assertTrue(
            ModerationAudit.objects.filter(
                action=ModerationAudit.Action.SUBMISSION_BULK,
                actor=self.staff,
            ).exists()
        )

    def test_bulk_approve_is_not_supported(self):
        response = self.client.post(
            reverse("accounts:bulk-moderation"),
            {
                "submission_ids": [str(self.first.pk)],
                "action": "approve",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Submission.Status.PENDING)


class DisputeWorkflowTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(
            username="case-member", password="test-pass-123"
        )
        self.staff = get_user_model().objects.create_user(
            username="case-reviewer", password="test-pass-123", is_staff=True
        )
        self.dog = Dog.objects.create(
            name="Contested Dog",
            slug="contested-dog",
            colour="Black",
            is_public=True,
        )

    def test_opening_dispute_does_not_change_canonical_dog(self):
        self.client.force_login(self.member)
        response = self.client.post(
            reverse("accounts:open-dispute", args=[self.dog.pk]),
            {
                "reason": DisputeCase.Reason.PEDIGREE,
                "details": "The listed sire may be incorrect.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.colour, "Black")
        dispute = DisputeCase.objects.get(opened_by=self.member)
        self.assertEqual(dispute.status, DisputeCase.Status.OPEN)
        self.assertTrue(
            ModerationAudit.objects.filter(
                action=ModerationAudit.Action.DISPUTE_OPENED,
                dispute=dispute,
            ).exists()
        )

    def test_moderator_resolution_is_audited(self):
        dispute = DisputeCase.objects.create(
            dog=self.dog,
            opened_by=self.member,
            reason=DisputeCase.Reason.IDENTITY,
            details="Identity needs review.",
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("accounts:review-dispute", args=[dispute.pk, "resolve"]),
            {"resolution_notes": "Identity confirmed from source evidence."},
        )

        self.assertEqual(response.status_code, 302)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, DisputeCase.Status.RESOLVED)
        self.assertEqual(dispute.closed_by, self.staff)
        self.assertTrue(
            ModerationAudit.objects.filter(
                action=ModerationAudit.Action.DISPUTE_UPDATED,
                dispute=dispute,
                actor=self.staff,
            ).exists()
        )


class ModerationQueueTests(TestCase):
    def test_queue_batches_reference_labels(self):
        staff = get_user_model().objects.create_user(
            username="queue-batch-reviewer",
            is_staff=True,
        )
        member = get_user_model().objects.create_user(username="queue-batch-member")
        kennel = Kennel.objects.create(name="Queue Kennel", slug="queue-kennel")
        sire = Dog.objects.create(name="Queue Sire", slug="queue-sire", sex=Dog.Sex.MALE)
        dam = Dog.objects.create(name="Queue Dam", slug="queue-dam", sex=Dog.Sex.FEMALE)
        litter = Litter.objects.create(
            kennel=kennel,
            code="QUEUE-LITTER",
            sire=sire,
            dam=dam,
        )
        Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=member,
            kennel=kennel,
            payload={
                "name": "Queue Dog",
                "sire_id": str(sire.pk),
                "dam_id": str(dam.pk),
                "litter_id": str(litter.pk),
            },
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:moderation"))

        self.assertEqual(response.status_code, 200)
        diff = {
            row["field"]: row["after"]
            for row in response.context["pending"][0].review_diff
        }
        self.assertEqual(diff["Sire"], "Queue Sire")
        self.assertEqual(diff["Dam"], "Queue Dam")
        self.assertEqual(diff["Litter"], "QUEUE-LITTER")

    def test_queue_prioritises_urgent_items(self):
        staff = get_user_model().objects.create_user(
            username="queue-reviewer", password="test-pass-123", is_staff=True
        )
        member = get_user_model().objects.create_user(username="queue-member")
        normal = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=member,
            payload={"name": "Normal Item"},
            priority=Submission.Priority.NORMAL,
        )
        urgent = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=member,
            payload={"name": "Urgent Item"},
            priority=Submission.Priority.URGENT,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:moderation"))

        self.assertEqual(response.status_code, 200)
        pending = response.context["pending"]
        self.assertEqual(pending[0].pk, urgent.pk)
        self.assertEqual(pending[1].pk, normal.pk)
