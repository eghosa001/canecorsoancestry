"""Focused role, status, and deep-link checks for staff review signals."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import (
    DisputeCase, Dog, ModerationAudit, ModerationRoleAssignment, Submission,
)


class StaffReviewAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.owner = users.objects.create_superuser(
            username="alerts-owner", password="OwnerTest!123"
        )
        cls.senior = users.objects.create_user(username="alerts-senior")
        cls.moderator = users.objects.create_user(username="alerts-reviewer")
        cls.member = users.objects.create_user(username="alerts-member")
        for staff, role in (
            (cls.owner, ModerationRoleAssignment.Role.OWNER),
            (cls.senior, ModerationRoleAssignment.Role.SENIOR),
            (cls.moderator, ModerationRoleAssignment.Role.REVIEWER),
        ):
            ModerationRoleAssignment.objects.create(
                user=staff, role=role, assigned_by=cls.owner
            )
        cls.dog = Dog.objects.create(name="Staff Alert Dog", slug="staff-alert-dog")
        cls.submission = Submission.objects.create(
            kind=Submission.Kind.DOG, submitted_by=cls.member, dog=cls.dog,
        )
        cls.dispute = DisputeCase.objects.create(
            dog=cls.dog, opened_by=cls.member,
            reason=DisputeCase.Reason.IDENTITY, details="Review identity documents",
        )

    def test_staff_roles_see_current_cases_and_exact_links(self):
        for user in (self.owner, self.senior, self.moderator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 200)
                alerts = response.context["staff_review_alerts"]
                self.assertEqual(alerts["total"], 2)
                self.assertEqual(alerts["submission_count"], 1)
                self.assertEqual(alerts["dispute_count"], 1)
                self.assertContains(
                    response, reverse("accounts:moderation-submission", args=(self.submission.pk,))
                )
                self.assertContains(response, "#dispute-" + str(self.dispute.pk))
                self.assertContains(response, "staff-review-bell")
                self.assertContains(response, "staff-review-mobile-indicator")

    def test_member_and_disabled_moderator_get_no_staff_signal(self):
        self.client.force_login(self.member)
        page = self.client.get(reverse("home"))
        self.assertIsNone(page.context["staff_review_alerts"])
        self.assertNotContains(page, "staff-review-bell")
        self.moderator.ancestry_moderation_role.is_deregistered = True
        self.moderator.ancestry_moderation_role.save(update_fields=("is_deregistered",))
        self.client.force_login(self.moderator)
        page = self.client.get(reverse("home"))
        self.assertIsNone(page.context["staff_review_alerts"])
        self.assertNotContains(page, "staff-review-bell")

    def test_signal_disappears_when_all_cases_are_closed(self):
        self.client.force_login(self.senior)
        self.submission.status = Submission.Status.APPROVED
        self.submission.save(update_fields=("status",))
        self.dispute.status = DisputeCase.Status.RESOLVED
        self.dispute.save(update_fields=("status",))
        response = self.client.get(reverse("home"))
        alerts = response.context["staff_review_alerts"]
        self.assertEqual(alerts["total"], 0)
        self.assertFalse(alerts["has_pending"])
        self.assertNotContains(response, "#dispute-" + str(self.dispute.pk))

    def test_protected_proposal_is_signalled_only_to_owner(self):
        event = ModerationAudit.objects.create(
            action=ModerationAudit.Action.RECORD_CHANGED,
            actor=self.moderator,
            dog=self.dog,
            summary={"kind": "direct_dog_proposal", "before_protected": {}, "proposed_changes": {}},
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("home"))
        alerts = response.context["staff_review_alerts"]
        self.assertEqual(alerts["total"], 3)
        self.assertEqual(alerts["display_count"], "3+")
        self.assertContains(response, reverse("accounts:dog-direct-edit", args=(self.dog.pk,)))
        self.client.force_login(self.senior)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["staff_review_alerts"]["total"], 2)
        self.assertNotContains(response, "Protected pedigree change · Super Admin")
        ModerationAudit.objects.create(
            action=ModerationAudit.Action.RECORD_CHANGED,
            actor=self.owner,
            dog=self.dog,
            summary={"kind": "direct_dog_proposal_approved", "original_audit_id": str(event.pk)},
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("home"))
        self.assertFalse(response.context["staff_review_alerts"]["protected_pending"])
