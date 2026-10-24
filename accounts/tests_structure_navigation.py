"""Role-aware navigation and page hierarchy contracts.

Keep complex tools reachable without expanding every admin action on arrival.
These assertions accompany WebKit layout tests rather than replacing them.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import ModerationRoleAssignment


class StructuredNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.member = users.objects.create_user(username="structure-member")
        cls.moderator = users.objects.create_user(username="structure-reviewer")
        cls.owner = users.objects.create_superuser(
            username="structure-owner", password="structure-owner-only-test"
        )
        ModerationRoleAssignment.objects.create(
            user=cls.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=cls.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=cls.owner, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=cls.owner,
        )

    def test_shared_structure_is_loaded_on_public_and_member_pages(self):
        for view in ("home", "registry:dog-search", "registry:kennel-list",
                     "pedigrees:index", "registry:statistics"):
            with self.subTest(view=view):
                response = self.client.get(reverse(view))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "structured-pages.css")
                self.assertContains(response, "structured-nav.js")
                self.assertContains(response, 'id="main-content"')

    def test_member_nav_prioritizes_routes_and_groups_secondary_tools(self):
        self.client.force_login(self.member)
        for name, section in (
            ("accounts:documents", "documents"),
            ("accounts:my-disputes", "disputes"),
            ("accounts:saved-pairings", "research"),
            ("accounts:notifications", "notifications"),
            ("accounts:profile", "profile"),
        ):
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["workspace_section"], section)
                self.assertContains(response, "workspace-nav-disclosure")
                self.assertContains(response, "workspace-more")
                self.assertContains(response, 'aria-label="Member workspace"')
                self.assertContains(response, 'aria-current="page"')
                self.assertNotContains(response, 'href="/admin/"')
                self.assertNotContains(response, 'href="/member/moderation/dogs/"')

    def test_moderator_actions_stay_separate_from_owner_controls(self):
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("accounts:moderation"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Other review tools")
        self.assertContains(response, "workspace-more")
        self.assertContains(response, 'href="/member/moderation/dogs/"')
        self.assertNotContains(response, "Advanced admin")
        self.assertNotContains(response, 'href="/admin/"')
        self.assertNotContains(response, "Administration tools")

    def test_owner_can_reach_all_protected_navigation_without_primary_crowding(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("Administration tools", html)
        self.assertIn(">Review queue</a>", html)
        self.assertIn('href="/member/moderation/merge-dogs/"', html)
        self.assertIn('href="/admin/"', html)
        self.assertLess(html.index('class="moderation-summary"'), html.index('id="staff-access"'))
        self.assertLess(html.index('id="staff-access"'), html.index('id="staff-accounts"'))
        self.assertIn("Moderator access", html)
        self.assertIn('id="staff-access-form"', html)

    def test_owner_tool_context_highlight_is_correct(self):
        self.client.force_login(self.owner)
        for name, section in (
            ("accounts:dog-direct-create", "dog_new"),
            ("accounts:health-genetic-list", "health_dna"),
            ("accounts:merge-dogs", "merge"),
            ("accounts:data-health", "health"),
            ("accounts:moderation-audit", "audit"),
        ):
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["workspace_section"], section)
                self.assertContains(response, 'aria-current="page"')
