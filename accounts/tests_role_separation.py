from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from registry.models import (
    ModerationRoleAssignment,
    Submission,
)
from registry.permissions import (
    can_manage_verification,
    can_review_flagged_submissions,
    can_review_submissions,
    can_use_member_features,
)


class StrictRoleSeparationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            username="role-owner",
            email="role-owner@example.com",
            password="Owner-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=self.owner,
            role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.owner,
        )

    def test_member_account_cannot_receive_moderation_assignment(self):
        member = get_user_model().objects.create_user(
            username="member-kennel",
            email="member-kennel@example.com",
            password="Member-pass-123",
        )
        Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=member,
            payload={"name": "Member Kennel", "slug": "member-kennel"},
        )

        with self.assertRaises(ValidationError):
            ModerationRoleAssignment.objects.create(
                user=member,
                role=ModerationRoleAssignment.Role.REVIEWER,
                assigned_by=self.owner,
            )

        self.assertFalse(can_review_submissions(member))
        self.assertTrue(can_use_member_features(member))

    def test_super_admin_creates_separate_non_django_staff_moderator_account(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:moderation-create-account"),
            {
                "username": "dedicated-moderator",
                "email": "dedicated-moderator@example.com",
                "role": ModerationRoleAssignment.Role.REVIEWER,
                "password1": "Moderator-pass-123",
                "password2": "Moderator-pass-123",
            },
        )

        self.assertEqual(response.status_code, 302)
        moderator = get_user_model().objects.get(username="dedicated-moderator")
        self.assertFalse(moderator.is_staff)
        self.assertFalse(moderator.is_superuser)
        self.assertEqual(
            moderator.ancestry_moderation_role.role,
            ModerationRoleAssignment.Role.REVIEWER,
        )
        self.assertTrue(can_review_submissions(moderator))
        self.assertFalse(can_review_flagged_submissions(moderator))
        self.assertFalse(can_use_member_features(moderator))

    def test_staff_account_is_redirected_from_member_dashboard_and_blocked_from_member_profile(self):
        moderator = get_user_model().objects.create_user(
            username="separate-moderator",
            email="separate-moderator@example.com",
            password="Moderator-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=moderator,
            role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        self.client.force_login(moderator)

        dashboard = self.client.get(reverse("dashboard"))
        profile = self.client.get(reverse("accounts:profile"))
        django_admin = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            dashboard,
            reverse("accounts:moderation"),
            fetch_redirect_response=False,
        )
        self.assertEqual(profile.status_code, 403)
        self.assertEqual(django_admin.status_code, 302)

    def test_role_capabilities_are_distinct(self):
        moderator = get_user_model().objects.create_user(username="role-moderator")
        senior = get_user_model().objects.create_user(username="role-senior")
        ModerationRoleAssignment.objects.create(
            user=moderator,
            role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=senior,
            role=ModerationRoleAssignment.Role.SENIOR,
            assigned_by=self.owner,
        )

        self.assertTrue(can_review_submissions(moderator))
        self.assertFalse(can_review_flagged_submissions(moderator))
        self.assertFalse(can_manage_verification(moderator))

        self.assertTrue(can_review_submissions(senior))
        self.assertTrue(can_review_flagged_submissions(senior))
        self.assertFalse(can_manage_verification(senior))

        self.assertTrue(can_review_submissions(self.owner))
        self.assertTrue(can_review_flagged_submissions(self.owner))
        self.assertTrue(can_manage_verification(self.owner))

    def test_member_cannot_be_promoted_through_role_management_endpoint(self):
        member = get_user_model().objects.create_user(
            username="cannot-promote-member",
            email="cannot-promote-member@example.com",
            password="Member-pass-123",
        )
        Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=member,
            payload={"name": "Cannot Promote", "slug": "cannot-promote"},
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:moderation-set-role"),
            {
                "user_id": member.pk,
                "role": ModerationRoleAssignment.Role.REVIEWER,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ModerationRoleAssignment.objects.filter(user=member).exists()
        )
        member.refresh_from_db()
        self.assertFalse(member.is_staff)
        self.assertFalse(member.is_superuser)
