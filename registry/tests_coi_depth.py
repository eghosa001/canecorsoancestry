"""Focused public profile COI depth, membership, and Safari navigation tests."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.template.defaultfilters import floatformat
from django.test import TestCase
from django.urls import reverse

from registry.admin import DogAdmin
from registry.models import Dog, ModerationRoleAssignment
from pedigrees.services import public_profile_coi


class DogProfileCoiDepthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # The common sire/dam ancestor is beyond generation 8 on one side.
        shared = Dog.objects.create(name="Depth Founder", slug="depth-founder", is_public=True)
        sire = Dog.objects.create(name="Depth Sire", slug="depth-sire", sire=shared, is_public=True)
        deep = shared
        for level in range(8):
            deep = Dog.objects.create(
                name=f"Depth branch {level}", slug=f"depth-branch-{level}",
                sire=deep, is_public=True,
            )
        dam = Dog.objects.create(name="Depth Dam", slug="depth-dam", sire=deep, is_public=True)
        cls.dog = Dog.objects.create(
            name="Depth Subject", slug="depth-subject", sire=sire, dam=dam, is_public=True,
        )
        cls.url = reverse("registry:dog-detail", args=[cls.dog.slug])

    def test_profile_defaults_to_all_recorded_ancestors(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "COI (all available generations)")
        self.assertGreater(response.context["coi_percent"], 0)
        self.assertFalse(response.context["can_select_coi"])

    def test_admin_public_coi_matches_frontend_default_exactly(self):
        public_response = self.client.get(self.url)
        public_value = public_response.context["coi_percent"]
        admin_result = public_profile_coi(self.dog, generations=None)
        admin_view = DogAdmin(Dog, admin.site)
        self.assertEqual(admin_result["coi_percent"], public_value)
        self.assertEqual(admin_result["coi_display_state"], "estimated")
        formatted = "<0.01%" if admin_result["coi_below_display_precision"] else f"{floatformat(public_value, 2)}%"
        self.assertIn(formatted, str(admin_view.public_coi_display(self.dog)))
        self.assertIn("public_coi_display", admin_view.get_readonly_fields(None, self.dog))

    def test_admin_and_frontend_both_refuse_unpublished_parentage(self):
        self.dog.dam.is_public = False
        self.dog.dam.save(update_fields=["is_public"])
        self.dog.refresh_from_db()
        frontend = self.client.get(self.url)
        admin_result = public_profile_coi(self.dog, generations=None)
        admin_text = str(DogAdmin(Dog, admin.site).public_coi_display(self.dog))
        self.assertIsNone(frontend.context["coi_percent"])
        self.assertEqual(frontend.context["coi_display_state"], "insufficient")
        self.assertEqual(admin_result["coi_percent"], frontend.context["coi_percent"])
        self.assertIn(frontend.context["coi_error"], admin_text)

    def test_admin_all_depth_does_not_inherit_a_member_comparison_filter(self):
        user = get_user_model().objects.create_user(username="coi-admin-parity-member")
        self.client.force_login(user)
        limited = self.client.get(self.url, {"coi_generations": "2"})
        self.assertEqual(limited.context["coi_percent"], 0)
        full = self.client.get(self.url)
        admin_result = public_profile_coi(self.dog)
        self.assertGreater(admin_result["coi_percent"], 0)
        self.assertEqual(full.context["coi_percent"], admin_result["coi_percent"])

    def test_members_can_select_two_four_six_or_eight_then_restore_all(self):
        member = get_user_model().objects.create_user(
            username="coi-depth-member", password="test-only-password",
        )
        self.client.force_login(member)
        for depth in (2, 4, 6, 8):
            with self.subTest(depth=depth):
                response = self.client.get(self.url, {"coi_generations": depth})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["coi_percent"], 0)
                self.assertContains(response, f"COI ({depth} generations)")
        default = self.client.get(self.url, {"coi_generations": "all"})
        self.assertGreater(default.context["coi_percent"], 0)
        self.assertContains(default, 'value="2"')
        self.assertContains(default, 'value="4"')
        self.assertContains(default, 'value="6"')
        self.assertContains(default, 'class="profile-coi-selection"')
        self.assertContains(default, 'class="btn btn-outline profile-coi-recalculate"')
        html = default.content.decode("utf-8")
        self.assertLess(
            html.index('id="profile-coi-generations"'),
            html.index('profile-coi-recalculate'),
        )

    def test_member_pedigree_keeps_all_depth_coi_when_board_shows_four(self):
        member = get_user_model().objects.create_user(
            username="coi-pedigree-member", password="test-only-password",
        )
        self.client.force_login(member)
        report_url = reverse("pedigrees:detail", args=[self.dog.slug])
        full = self.client.get(report_url, {"generations": "4"})
        self.assertEqual(full.status_code, 200)
        self.assertGreater(full.context["analysis"]["coi_percent"], 0)
        self.assertContains(full, 'value="all" selected')
        short = self.client.get(report_url, {
            "generations": "4", "coi_generations": "2",
        })
        self.assertEqual(short.context["analysis"]["coi_percent"], 0)
        self.assertContains(short, 'value="2" selected')

    def test_guest_query_cannot_change_public_coi(self):
        default = self.client.get(self.url)
        overridden = self.client.get(self.url, {"coi_generations": "2"})
        self.assertEqual(default.context["coi_percent"], overridden.context["coi_percent"])
        self.assertNotContains(overridden, 'id="profile-coi-generations"')

    def test_mobile_safari_browse_link_resolves_to_published_profile(self):
        safari = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile Safari/604.1")
        result = self.client.get(
            reverse("registry:dog-search"), {"q": "Depth Subject"}, HTTP_USER_AGENT=safari,
        )
        self.assertContains(result, self.url + "?source=search")
        linked = self.client.get(self.url + "?source=search", HTTP_USER_AGENT=safari)
        self.assertEqual(linked.status_code, 200)
        self.assertContains(linked, "Depth Subject")

    def test_active_admin_and_moderators_can_compare_on_mobile(self):
        users = get_user_model().objects
        admin = users.create_superuser(
            username="coi-depth-admin", email="admin@example.test", password="test-password",
        )
        reviewer = users.create_user(username="coi-depth-reviewer")
        senior = users.create_user(username="coi-depth-senior")
        for user, role in (
            (reviewer, ModerationRoleAssignment.Role.REVIEWER),
            (senior, ModerationRoleAssignment.Role.SENIOR),
        ):
            ModerationRoleAssignment.objects.create(user=user, role=role)

        pedigree_url = reverse("pedigrees:detail", args=[self.dog.slug])
        mobile_agents = (
            "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1",
        )
        for user in (admin, reviewer, senior):
            self.client.force_login(user)
            for agent in mobile_agents:
                with self.subTest(user=user.username, browser=agent.split("(")[1].split(")")[0]):
                    response = self.client.get(
                        self.url, {"coi_generations": "2"}, HTTP_USER_AGENT=agent,
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context["can_select_coi"])
                    self.assertContains(response, 'id="profile-coi-generations"')
                    self.assertContains(response, "COI (2 generations)")
                    self.assertEqual(response.context["coi_percent"], 0)
                    pedigree = self.client.get(
                        pedigree_url, {"generations": 4, "coi_generations": 2},
                        HTTP_USER_AGENT=agent,
                    )
                    self.assertEqual(pedigree.status_code, 200)
                    self.assertContains(pedigree, 'value="2" selected')
                    pairing = self.client.get(
                        reverse("pedigrees:virtual-mating"), HTTP_USER_AGENT=agent,
                    )
                    self.assertEqual(pairing.status_code, 200)
                    self.assertFalse(pairing.context["can_save_research"])
            self.client.logout()

    def test_suspended_moderator_cannot_change_coi_depth(self):
        user = get_user_model().objects.create_user(username="coi-suspended-moderator")
        ModerationRoleAssignment.objects.create(
            user=user, role=ModerationRoleAssignment.Role.NONE,
        )
        self.client.force_login(user)
        profile = self.client.get(self.url, {"coi_generations": "2"})
        self.assertEqual(profile.status_code, 200)
        self.assertFalse(profile.context["can_select_coi"])
        self.assertGreater(profile.context["coi_percent"], 0)
        self.assertNotContains(profile, 'id="profile-coi-generations"')
        pedigree_url = reverse("pedigrees:detail", args=[self.dog.slug])
        self.assertEqual(self.client.get(pedigree_url).status_code, 403)
