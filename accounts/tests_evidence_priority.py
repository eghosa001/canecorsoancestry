"""Staff evidence triage: useful ordering without leaking hidden records."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import Dog, DogSource, ModerationRoleAssignment, VerificationState


class StaffEvidencePriorityTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:data-health-evidence")
        self.staff_user = get_user_model().objects.create_user(
            username="evidence-reviewer-priority", password="StrongTestPassword123!"
        )
        ModerationRoleAssignment.objects.create(
            user=self.staff_user,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.client.force_login(self.staff_user)

    def test_popular_first_and_alphabetical_switch(self):
        low = Dog.objects.create(name="Alpha Archive", slug="alpha-archive", is_public=True, search_count=1)
        high = Dog.objects.create(name="Zeta Archive", slug="zeta-archive", is_public=True, search_count=900)
        popular = self.client.get(self.url)
        self.assertEqual(popular.status_code, 200)
        self.assertEqual(
            [dog.pk for dog in popular.context["dogs"]][:2],
            [high.pk, low.pk],
        )
        alphabetic = self.client.get(self.url, {"sort": "name"})
        self.assertEqual(alphabetic.status_code, 200)
        self.assertEqual(
            [dog.pk for dog in alphabetic.context["dogs"]][:2],
            [low.pk, high.pk],
        )
        self.assertContains(popular, "Most searched first")

    def test_public_worklist_excludes_moderation_hidden(self):
        Dog.objects.create(name="Visible", slug="visible-review", is_public=True)
        Dog.objects.create(
            name="Hidden", slug="hidden-review",
            is_public=True, hidden_by_moderation=True,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        slugs = {dog.slug for dog in response.context["dogs"]}
        self.assertIn("visible-review", slugs)
        self.assertNotIn("hidden-review", slugs)

    def test_reviewed_status_cross_check_does_not_change_verification(self):
        candidate = Dog.objects.create(
            name="Needs Documentary Crosscheck", slug="needs-crosscheck",
            is_public=True, verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        verified = Dog.objects.create(
            name="Source Reviewed", slug="source-reviewed",
            is_public=True, verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        DogSource.objects.create(
            dog=verified, title="Reviewed archive",
            source_type=DogSource.SourceType.PEDIGREE,
            source_url="https://example.org/archive", verified_at=timezone.now(),
        )
        response = self.client.get(
            self.url, {"issue": "reviewed-status-needs-source-check"}
        )
        self.assertEqual(response.status_code, 200)
        slugs = {dog.slug for dog in response.context["dogs"]}
        self.assertEqual(slugs, {candidate.slug})
        self.assertContains(response, "Other approved evidence may exist")
        candidate.refresh_from_db()
        self.assertEqual(candidate.verification_state, VerificationState.PEDIGREE_REVIEWED)

    def test_invalid_sort_rejected(self):
        self.assertEqual(self.client.get(self.url, {"sort": "random"}).status_code, 400)

    def test_regular_member_cannot_access_worklist(self):
        member = get_user_model().objects.create_user(
            username="evidence-member-priority", password="StrongTestPassword123!"
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_priority_queue_ranks_conflicts_and_approval_cross_checks(self):
        from registry.models import DisputeCase, ModerationAudit

        sire = Dog.objects.create(
            name="Parent Recorded Female", slug="priority-sire",
            sex=Dog.Sex.FEMALE, is_public=True,
        )
        dam = Dog.objects.create(
            name="Other Parent", slug="priority-dam",
            sex=Dog.Sex.FEMALE, is_public=True,
        )
        dispute = Dog.objects.create(
            name="Disputed Parentage", slug="priority-disputed",
            is_public=True, sire=sire, dam=dam, search_count=1,
        )
        DisputeCase.objects.create(
            dog=dispute, opened_by=self.staff_user,
            reason=DisputeCase.Reason.PEDIGREE,
            details="Two parents reference the same dog; human investigation required.",
        )
        historical = Dog.objects.create(
            name="Historical Approval", slug="historical-approval",
            is_public=True, search_count=30,
        )
        ModerationAudit.objects.create(
            actor=self.staff_user, dog=historical,
            action=ModerationAudit.Action.SUBMISSION_APPROVED,
            note="Earlier approval only; review supporting documents.",
        )
        source_reviewed = Dog.objects.create(
            name="Source Has Review Marker", slug="source-has-review",
            is_public=True, search_count=900,
        )
        DogSource.objects.create(
            dog=source_reviewed, source_type=DogSource.SourceType.PEDIGREE,
            title="Real document", source_url="https://example.org/pedigree",
            verified_at=timezone.now(),
        )
        health_only = Dog.objects.create(
            name="Reviewed Health Only", slug="health-not-parentage",
            is_public=True, sire=sire, dam=dam,
        )
        DogSource.objects.create(
            dog=health_only, source_type=DogSource.SourceType.HEALTH,
            title="Health results, not parentage", source_url="https://example.org/health",
            verified_at=timezone.now(),
        )
        result = self.client.get(self.url, {"issue": "priority"})
        self.assertEqual(result.status_code, 200)
        rows = list(result.context["dogs"])
        self.assertEqual(rows[0].pk, dispute.pk)
        self.assertTrue(rows[0].priority_has_conflict)
        indexed = {dog.slug: dog for dog in rows}
        self.assertTrue(indexed[historical.slug].priority_has_approval_audit)
        self.assertFalse(indexed[historical.slug].priority_has_reviewed_document)
        self.assertTrue(indexed[source_reviewed.slug].priority_has_reviewed_document)
        self.assertFalse(indexed[health_only.slug].priority_has_reviewed_parentage)
        self.assertContains(result, "Triage priority")
        self.assertContains(result, "Audit history")
        approval = self.client.get(self.url, {"issue": "approval-cross-check"})
        approved_ids = {dog.pk for dog in approval.context["dogs"]}
        self.assertIn(historical.pk, approved_ids)
        self.assertNotIn(source_reviewed.pk, approved_ids)
        historical.refresh_from_db()
        self.assertEqual(historical.verification_state, VerificationState.COMMUNITY)

    def test_cross_dog_photo_hash_detected_but_not_same_dog_repeat(self):
        from registry.models import DogImage

        first = Dog.objects.create(name="First Reused Photo", slug="first-reused-photo", is_public=True)
        second = Dog.objects.create(name="Second Reused Photo", slug="second-reused-photo", is_public=True)
        private = Dog.objects.create(name="Unpublished Photo", slug="unpublished-reused-photo", is_public=False)
        duplicate_hash = "a" * 64
        DogImage.objects.create(dog=first, image="dogs/test/first.jpg", content_sha256=duplicate_hash)
        DogImage.objects.create(dog=first, image="dogs/test/same-dog.jpg", content_sha256=duplicate_hash)
        DogImage.objects.create(dog=private, image="dogs/test/private.jpg", content_sha256=duplicate_hash)
        before = self.client.get(self.url, {"issue": "shared-photo"})
        self.assertNotIn(first.pk, [dog.pk for dog in before.context["dogs"]])
        DogImage.objects.create(dog=second, image="dogs/test/second.jpg", content_sha256=duplicate_hash)
        after = self.client.get(self.url, {"issue": "shared-photo"})
        self.assertEqual({dog.pk for dog in after.context["dogs"]}, {first.pk, second.pk})
        self.assertContains(after, "This can be legitimate")
        self.assertNotContains(after, private.slug)

    def test_cohort_excludes_private_and_kennel_hidden_records(self):
        from registry.models import Kennel

        hidden = Dog.objects.create(
            name="Moderation Hidden", slug="moderation-hidden-high",
            is_public=True, hidden_by_moderation=True, search_count=100000,
        )
        private = Dog.objects.create(
            name="Private Viral Record", slug="private-viral-record",
            is_public=False, search_count=100001,
        )
        kennel = Kennel.objects.create(
            name="Visibility Locked Kennel", slug="visibility-locked-kennel",
            hide_dogs=True,
        )
        kennel_hidden = Dog.objects.create(
            name="Kennel Hidden", slug="kennel-hidden-high",
            kennel=kennel, is_public=True, search_count=200000,
        )
        response = self.client.get(self.url, {"issue": "priority"})
        self.assertEqual(response.status_code, 200)
        ids = {dog.pk for dog in response.context["dogs"]}
        self.assertNotIn(hidden.pk, ids)
        self.assertNotIn(private.pk, ids)
        self.assertNotIn(kennel_hidden.pk, ids)

    def test_new_filters_deny_regular_member(self):
        member = get_user_model().objects.create_user(username="untrusted-priority-reviewer")
        self.client.force_login(member)
        for issue in ("priority", "approval-cross-check", "shared-photo"):
            with self.subTest(issue=issue):
                self.assertEqual(self.client.get(self.url, {"issue": issue}).status_code, 403)
