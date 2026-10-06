from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from registry.models import Kennel, KennelMembership


class DashboardTests(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_shows_linked_kennel(self):
        user = get_user_model().objects.create_user(username="breeder", password="test-pass-123")
        kennel = Kennel.objects.create(name="Custodi Nos", slug="custodi-nos")
        KennelMembership.objects.create(kennel=kennel, user=user, role=KennelMembership.Role.OWNER)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Custodi Nos")



class PublicThemeRegressionTests(TestCase):
    def test_home_caches_public_statistics_under_the_read_key(self):
        cache.delete("cca:home:public-stats:v3")

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(cache.get("cca:home:public-stats:v3"))

    def test_home_restores_cca_plaque_and_theme_controls(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, "CANECORSOANCESTRY.COM")
        self.assertContains(response, "hero-mobile-break")
        self.assertContains(response, '<button class="theme-toggle', count=3)
        self.assertContains(response, "Countries")


class FormControlContrastTests(TestCase):
    def test_member_form_controls_follow_theme_and_native_choices_stay_legible(self):
        css_path = finders.find("core/site.css")
        self.assertIsNotNone(css_path)
        css = Path(css_path).read_text(encoding="utf-8")

        self.assertNotIn(
            ".form-field textarea,\n.merge-form select,\n.review-actions textarea {\n"
            "  width: 100%;\n  border: 1px solid var(--line-soft);\n"
            "  background: #090b0a;",
            css,
        )
        self.assertIn('input[type="file"]::file-selector-button', css)
        self.assertIn("select option,", css)
