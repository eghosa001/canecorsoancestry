"""Focused public profile COI depth, membership, and Safari navigation tests."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog


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
