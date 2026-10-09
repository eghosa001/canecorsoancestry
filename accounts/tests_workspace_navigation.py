"""Small route and role-navigation regressions.

Keep the public routes and existing role boundaries stable when admin/member
workspaces gain new navigation.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import get_resolver, reverse

from registry.models import ModerationRoleAssignment


class WorkspaceNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.member = User.objects.create_user(username="nav-member", email="member-nav@example.com")
        cls.moderator = User.objects.create_user(username="nav-moderator", email="mod-nav@example.com")
        cls.owner = User.objects.create_superuser(username="nav-owner", email="owner-nav@example.com", password="Owner!123456")
        ModerationRoleAssignment.objects.create(
            user=cls.moderator, role=ModerationRoleAssignment.Role.REVIEWER, assigned_by=cls.owner
        )
        ModerationRoleAssignment.objects.create(
            user=cls.owner, role=ModerationRoleAssignment.Role.OWNER, assigned_by=cls.owner
        )

    def test_no_duplicate_explicit_authentication_routes(self):
        patterns = [str(pattern.pattern) for pattern in get_resolver().url_patterns]
        for path in ("accounts/login/", "accounts/logout/", "accounts/password_reset/",
                     "accounts/password_reset/done/", "accounts/password_change/",
                     "accounts/password_change/done/", "accounts/reset/<uidb64>/<token>/",
                     "accounts/reset/done/"):
            with self.subTest(path=path):
                self.assertEqual(patterns.count(path), 1)
        self.assertEqual(reverse("login"), "/accounts/login/")
        self.assertEqual(reverse("password_reset"), "/accounts/password_reset/")
        self.assertEqual(reverse("password_reset_confirm", kwargs={
            "uidb64": "aQ", "token": "test-token",
        }), "/accounts/reset/aQ/test-token/")

    def test_member_subpage_has_member_links_without_staff_links(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("accounts:submissions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Member workspace"')
        self.assertContains(response, 'href="/member/pedigrees/"')
        self.assertContains(response, 'href="/member/litters/"')
        self.assertContains(response, 'href="/member/submissions/" aria-current="page"')
        self.assertNotContains(response, 'href="/member/moderation/dogs/"')
        self.assertNotContains(response, 'href="/admin/"')

    def test_member_overview_keeps_its_single_dashboard_sidebar(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dashboard-sidebar")
        self.assertNotContains(response, 'class="workspace-shortcuts"')

    def test_moderator_subpage_links_back_to_relevant_staff_sections(self):
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("accounts:dog-edit-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Staff workspace"')
        self.assertContains(response, 'href="/member/moderation/dogs/" aria-current="page"')
        self.assertContains(response, 'href="/member/moderation/audit/"')
        self.assertNotContains(response, 'href="/admin/"')
        self.assertNotContains(response, 'href="/member/profile/"')
        self.assertEqual(self.client.get(reverse("accounts:verification-dashboard")).status_code, 403)

    def test_owner_has_verification_overview_and_advanced_admin(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/member/moderation/verification/" aria-current="page"')
        self.assertContains(response, 'href="/member/moderation/dogs/"')
        self.assertContains(response, 'href="/admin/"')
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_member_cannot_enter_staff_workspaces(self):
        self.client.force_login(self.member)
        for view in ("accounts:moderation", "accounts:dog-edit-list", "accounts:moderation-audit",
                     "accounts:verification-dashboard"):
            with self.subTest(view=view):
                self.assertEqual(self.client.get(reverse(view)).status_code, 403)
