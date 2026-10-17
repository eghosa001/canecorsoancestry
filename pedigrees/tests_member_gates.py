"""Private analysis HTTP gates: exercise only the changed member boundary."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog


class MemberAnalysisGateTests(TestCase):
    def setUp(self):
        self.sire = Dog.objects.create(
            name="Gate Sire", slug="gate-sire", sex=Dog.Sex.MALE, is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Gate Dam", slug="gate-dam", sex=Dog.Sex.FEMALE, is_public=True,
        )
        self.pairing = reverse("pedigrees:virtual-mating")
        self.member = get_user_model().objects.create_user(
            username="gate-member", password="pass12345",
        )

    @patch("pedigrees.views.virtual_mating_analysis")
    def test_guest_can_select_dogs_but_cannot_compute(self, analysis):
        response = self.client.get(self.pairing, {
            "sire_q": self.sire.name,
            "dam_q": self.dam.name,
            "sire": str(self.sire.pk),
            "dam": str(self.dam.pk),
            "generations": 8,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register to start your pairing analysis")
        self.assertContains(response, f'action="{self.pairing}#mating-access"')
        self.assertContains(response, 'id="mating-access"')
        self.assertContains(response, "Gate Sire")
        self.assertContains(response, "Gate Dam")
        self.assertContains(response, "/member/signup/?next=")
        self.assertNotContains(response, "Projected offspring COI")
        analysis.assert_not_called()

    def test_member_can_run_pairing_after_login(self):
        self.client.force_login(self.member)
        response = self.client.get(self.pairing, {
            "sire": str(self.sire.pk), "dam": str(self.dam.pk),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projected offspring COI")

    def test_all_pedigree_analysis_and_export_routes_require_login(self):
        urls = (
            reverse("pedigrees:detail", args=[self.sire.slug]),
            reverse("pedigrees:export", args=[self.sire.slug]),
            reverse("pedigrees:reverse", args=[self.sire.slug]),
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("?next=", response.url)
        self.client.force_login(self.member)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_can_research_published_pedigrees_but_not_save_member_pairings(self):
        staff = get_user_model().objects.create_superuser(
            username="gate-staff", email="staff-gate@example.com",
            password="pass12345",
        )
        self.client.force_login(staff)
        pairing = self.client.get(self.pairing)
        self.assertEqual(pairing.status_code, 200)
        self.assertFalse(pairing.context["can_save_research"])
        self.assertEqual(
            self.client.get(reverse("pedigrees:detail", args=[self.sire.slug])).status_code,
            200,
        )
        self.assertEqual(self.client.post(reverse("accounts:save-pairing")).status_code, 403)

    def test_signed_in_reports_and_pairing_are_noindex(self):
        self.client.force_login(self.member)
        for url in (
            reverse("pedigrees:detail", args=[self.sire.slug]),
            self.pairing,
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("noindex", response["X-Robots-Tag"])
                self.assertContains(response, 'content="noindex,nofollow,noarchive"')

    def test_public_sitemap_does_not_list_login_protected_reports(self):
        from core.sitemaps import SITEMAPS
        self.assertNotIn("pedigrees", SITEMAPS)
        self.assertNotIn("descendants", SITEMAPS)
