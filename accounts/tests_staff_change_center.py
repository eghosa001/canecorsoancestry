"""Staff change center coverage: route integrity, roles and real mutations.

This deliberately exercises the same public Django view endpoints used by
the website rather than testing only that a navigation link was rendered.
"""
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from registry.models import (
    Dog, Kennel, ModerationAudit, ModerationRoleAssignment,
    Submission, SubmissionRiskLevel, VerificationRule,
)
from registry.permissions import can_review_submissions

from .staff_change_center import CATEGORIES


class StaffChangeCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.super_admin = User.objects.create_superuser(
            username="changes-super", email="changes-super@example.test",
            password="super-safe-test-password",
        )
        cls.moderator = User.objects.create_user(
            username="changes-moderator", password="moderator-safe-test-password",
        )
        cls.senior = User.objects.create_user(
            username="changes-senior", password="senior-safe-test-password",
        )
        cls.member = User.objects.create_user(
            username="changes-member", password="member-safe-test-password",
        )
        cls.django_staff = User.objects.create_user(
            username="changes-django-only", is_staff=True,
        )
        ModerationRoleAssignment.objects.create(
            user=cls.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=cls.super_admin,
        )
        ModerationRoleAssignment.objects.create(
            user=cls.senior, role=ModerationRoleAssignment.Role.SENIOR,
            assigned_by=cls.super_admin,
        )
        cls.kennel = Kennel.objects.create(
            name="Admin change kennel", slug="admin-change-kennel",
        )
        cls.dog = Dog.objects.create(
            name="Admin change dog", slug="admin-change-dog",
            kennel=cls.kennel, is_public=False,
        )

    def test_unauthorized_accounts_cannot_view_change_center(self):
        url = reverse("accounts:staff-change-center")
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.member, self.django_staff):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_all_action_urls_resolve_to_real_views_without_unsafe_relative_links(self):
        for section in CATEGORIES:
            for action in section["actions"]:
                with self.subTest(section=section["id"], action=action["title"]):
                    url = reverse(action["route"]) + action["query"] + action["fragment"]
                    parsed = urlsplit(url)
                    self.assertTrue(parsed.path.startswith("/"))
                    self.assertEqual(resolve(parsed.path).view_name, action["route"])
                    self.assertGreaterEqual(action["level"], 1)
                    self.assertLessEqual(action["level"], 3)
                    self.assertTrue(action["steps"].strip())

    def test_change_center_has_direct_workflow_steps_and_accessible_search_feedback(self):
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("accounts:staff-change-center"))
        self.assertEqual(response.status_code, 200)
        for label in (
            "1. Find the record", "2. Review and save", "3. Verify the result",
            "Find a dog", "Find a kennel", "Pending approvals",
        ):
            self.assertContains(response, label)
        self.assertContains(response, 'id="staff-center-result-count"')
        self.assertContains(response, 'id="staff-center-clear"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "staff-center-search-row")
        self.assertNotContains(response, "Staff permissions</a>")
        self.assertNotContains(response, 'href="/admin/"')

    def test_super_admin_has_direct_staff_permissions_shortcut(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("accounts:staff-change-center"))
        self.assertContains(response, ">Staff permissions</a>")
        self.assertContains(response, reverse("accounts:verification-dashboard") + "#staff-accounts")

    def test_canonical_editor_shows_edit_progress_and_collapsible_history(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("accounts:dog-direct-edit", args=[self.dog.pk]))
        self.assertEqual(response.status_code, 200)
        for target in ("dog-identity", "dog-related", "dog-save", "revision-history"):
            self.assertContains(response, 'id="' + target + '"')
            self.assertContains(response, 'href="#' + target + '"')
        self.assertContains(response, "staff-edit-flow.js")
        self.assertContains(response, "data-edit-form")
        self.assertContains(response, "data-edit-status")
        self.assertContains(response, "data-edit-dirty")
        self.assertContains(response, "staff-edit-revisions")
        self.assertContains(response, "Unsaved changes")
        self.assertContains(response, "Revision history and Super Admin review")

    def test_moderator_sees_real_edits_but_no_staff_control_or_admin_links(self):
        self.client.force_login(self.moderator)
        page = self.client.get(reverse("accounts:staff-change-center"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Find and edit any dog")
        self.assertContains(page, "Enter or change verified health numbers")
        self.assertContains(page, "Find and manage a kennel")
        self.assertContains(page, "Resolve disputes and photo corrections")
        self.assertContains(page, "Bulk assignments and priorities")
        self.assertNotContains(page, "Permanently deregister a moderator")
        self.assertNotContains(page, "Change verification rules")
        self.assertNotContains(page, reverse("admin:index"))
        self.assertNotContains(page, "Approve high-risk or second reviews")

    def test_senior_moderator_sees_high_risk_not_owner_controls(self):
        self.client.force_login(self.senior)
        page = self.client.get(reverse("accounts:staff-change-center"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Approve high-risk or second reviews")
        self.assertNotContains(page, "Change moderator permissions")
        self.assertNotContains(page, "Permanently deregister a moderator")
        self.assertNotContains(page, "Lock or unlock protected dogs and litters")

    def test_super_admin_sees_full_role_control_and_advanced_admin(self):
        self.client.force_login(self.super_admin)
        page = self.client.get(reverse("accounts:staff-change-center"))
        self.assertEqual(page.status_code, 200)
        for label in (
            "Create a Moderator or Senior Moderator", "Change moderator permissions",
            "Suspend or reactivate a moderator", "Permanently deregister a moderator",
            "Merge verified duplicate dogs", "Change verification rules",
            "Lock or unlock protected dogs and litters",
            "Edit approved litter records", "Manage kennel member roles",
            "Inspect payments and transaction records",
        ):
            with self.subTest(label=label):
                self.assertContains(page, label)
        self.assertContains(page, reverse("accounts:verification-dashboard") + "#staff-accounts")
        self.assertContains(page, reverse("admin:index"))

    def test_staff_navigation_and_deep_links_are_present(self):
        self.client.force_login(self.moderator)
        page = self.client.get(reverse("accounts:moderation"))
        self.assertContains(page, reverse("accounts:staff-change-center"))
        self.assertContains(page, 'id="record-verification"')
        self.assertContains(page, 'id="open-disputes"')
        self.assertContains(page, 'id="pending-review"')
        self.client.force_login(self.super_admin)
        dashboard = self.client.get(reverse("accounts:verification-dashboard"))
        for anchor in ("staff-access", "staff-accounts", "verification-rules", "record-locks"):
            self.assertContains(dashboard, 'id="' + anchor + '"')
        self.assertContains(dashboard, reverse("accounts:staff-change-center"))
        advanced = self.client.get(reverse("admin:index"))
        self.assertContains(advanced, "Change center")

    def test_actual_staff_permission_edit_suspension_and_reactivation(self):
        self.client.force_login(self.super_admin)
        change = reverse("accounts:moderation-set-role")
        response = self.client.post(change, {
            "user_id": str(self.moderator.pk),
            "role": ModerationRoleAssignment.Role.SENIOR,
        })
        self.assertEqual(response.status_code, 302)
        self.moderator.ancestry_moderation_role.refresh_from_db()
        self.assertEqual(
            self.moderator.ancestry_moderation_role.role,
            ModerationRoleAssignment.Role.SENIOR,
        )
        status = reverse("accounts:moderation-set-status")
        response = self.client.post(status, {
            "user_id": str(self.moderator.pk), "action": "deactivate",
            "reason": "Internal access review in progress",
        })
        self.assertEqual(response.status_code, 302)
        self.moderator.refresh_from_db()
        self.assertFalse(self.moderator.is_active)
        self.assertFalse(can_review_submissions(self.moderator))
        self.client.force_login(self.moderator)
        self.assertNotEqual(
            self.client.get(reverse("accounts:staff-change-center")).status_code, 200
        )
        self.client.force_login(self.super_admin)
        self.assertEqual(self.client.post(status, {
            "user_id": str(self.moderator.pk), "action": "activate",
            "reason": "Access review completed and approved",
        }).status_code, 302)
        self.moderator.refresh_from_db()
        self.assertTrue(self.moderator.is_active)
        self.assertTrue(can_review_submissions(self.moderator))

    def test_actual_permanent_deregistration_preserves_audit_and_denies_reentry(self):
        old_admin_number = self.moderator.ancestry_moderation_role.admin_number
        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("accounts:moderation-deregister-staff"),
            {"user_id": str(self.moderator.pk), "confirmation": "DEREGISTER",
             "reason": "Proven violation of staff access policy."},
        )
        self.assertEqual(response.status_code, 302)
        self.moderator.refresh_from_db()
        assignment = self.moderator.ancestry_moderation_role
        assignment.refresh_from_db()
        self.assertFalse(self.moderator.is_active)
        self.assertFalse(self.moderator.has_usable_password())
        self.assertTrue(assignment.is_deregistered)
        self.assertEqual(assignment.admin_number, old_admin_number)
        self.assertFalse(can_review_submissions(self.moderator))
        self.assertTrue(ModerationAudit.objects.filter(
            summary__type="moderation_account_deregistered",
            summary__target_admin_number=old_admin_number,
        ).exists())
        self.assertEqual(self.client.post(reverse("accounts:moderation-set-role"), {
            "user_id": str(self.moderator.pk), "role": "reviewer",
        }).status_code, 302)
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_deregistered)
        self.assertFalse(can_review_submissions(self.moderator))

    def test_real_record_lock_and_rule_change_are_super_admin_only(self):
        rule = VerificationRule.objects.create(
            code="change-center-validation", title="Site evidence rule",
            risk_level=SubmissionRiskLevel.YELLOW,
        )
        rule_url = reverse("accounts:verification-rule-update", args=[rule.pk])
        lock_url = reverse("accounts:moderation-record-lock")
        for user in (self.moderator, self.senior, self.member):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.post(rule_url, {
                    "risk_level": SubmissionRiskLevel.RED,
                    "second_approval_required": "on",
                }).status_code, 403)
                self.assertEqual(self.client.post(lock_url, {
                    "record_type": "dog", "record_id": str(self.dog.pk),
                    "action": "lock", "reason": "Document conflict review",
                }).status_code, 403)
        self.client.force_login(self.super_admin)
        self.assertEqual(self.client.post(rule_url, {
            "risk_level": SubmissionRiskLevel.RED,
            "second_approval_required": "on",
        }).status_code, 302)
        rule.refresh_from_db()
        self.assertEqual(rule.risk_level, SubmissionRiskLevel.RED)
        self.assertTrue(rule.second_approval_required)
        self.assertEqual(self.client.post(lock_url, {
            "record_type": "dog", "record_id": str(self.dog.pk),
            "action": "lock", "reason": "Document conflict review",
        }).status_code, 302)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_record_locked)
        self.assertEqual(self.client.post(lock_url, {
            "record_type": "dog", "record_id": str(self.dog.pk),
            "action": "unlock", "reason": "Document conflict resolved",
        }).status_code, 302)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_record_locked)

    def test_staff_can_reach_editors_but_not_super_admin_only_editors(self):
        common = (
            reverse("accounts:moderation"),
            reverse("accounts:dog-edit-list"),
            reverse("accounts:dog-direct-edit", args=[self.dog.pk]),
            reverse("accounts:reviewed-dog-health", args=[self.dog.pk]),
            reverse("accounts:kennel-publication-list"),
            reverse("accounts:kennel-publication-detail", args=[self.kennel.pk]),
            reverse("accounts:moderation-audit"),
            reverse("accounts:data-health"),
        )
        privileged = (
            reverse("accounts:verification-dashboard"),
            reverse("accounts:health-genetic-list"),
            reverse("accounts:merge-dogs"),
        )
        for user in (self.moderator, self.senior):
            with self.subTest(role=user.username):
                self.client.force_login(user)
                for url in common:
                    with self.subTest(url=url):
                        self.assertEqual(self.client.get(url).status_code, 200)
                for url in privileged:
                    with self.subTest(url=url):
                        self.assertEqual(self.client.get(url).status_code, 403)
                self.assertNotEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_moderator_cannot_edit_roles_or_remove_other_staff(self):
        for user in (self.moderator, self.senior, self.member):
            self.client.force_login(user)
            for route, fields in (
                ("accounts:moderation-set-role", {
                    "user_id": str(self.senior.pk), "role": "owner",
                }),
                ("accounts:moderation-set-status", {
                    "user_id": str(self.senior.pk), "action": "deactivate",
                    "reason": "Attempted privilege override",
                }),
                ("accounts:moderation-deregister-staff", {
                    "user_id": str(self.senior.pk),
                    "confirmation": "DEREGISTER",
                    "reason": "Attempted unauthorized staff removal",
                }),
            ):
                with self.subTest(user=user.username, route=route):
                    self.assertEqual(self.client.post(reverse(route), fields).status_code, 403)
        self.senior.refresh_from_db()
        self.assertTrue(self.senior.is_active)
        self.assertFalse(self.senior.ancestry_moderation_role.is_deregistered)
        self.assertEqual(
            self.senior.ancestry_moderation_role.role,
            ModerationRoleAssignment.Role.SENIOR,
        )
