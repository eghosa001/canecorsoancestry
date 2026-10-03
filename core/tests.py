from django.contrib.auth import get_user_model
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
    def test_home_restores_cca_plaque_and_theme_controls(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, "CANECORSOANCESTRY.COM")
        self.assertContains(response, "hero-mobile-break")
        self.assertContains(response, '<button class="theme-toggle', count=3)
        self.assertContains(response, "Countries")
