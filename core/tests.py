from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import Dog, DogImage, Kennel, KennelMembership


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

    def test_dashboard_gives_each_member_action_a_clear_purpose(self):
        user = get_user_model().objects.create_user(
            username="structured-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Structured Kennel",
            slug="structured-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            kennel=kennel,
            user=user,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="Structured Dog",
            slug="structured-dog",
            kennel=kennel,
            is_public=False,
        )
        DogImage.objects.create(
            dog=dog,
            image="dogs/private/structured-dog.jpg",
            is_primary=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What do you want to do?")
        self.assertContains(response, "Start dog submission")
        self.assertContains(response, "Manage existing records")
        self.assertContains(response, "Track review")
        self.assertContains(response, "Kennel verified")
        self.assertContains(response, "Structured Dog")
        self.assertContains(
            response,
            reverse("accounts:submit-image", args=[dog.pk]),
        )
        self.assertContains(
            response,
            reverse("accounts:submit-correction", args=[dog.pk]),
        )
        self.assertContains(
            response,
            reverse("accounts:submit-document", args=[dog.pk]),
        )



class AuthenticatedNavigationTests(TestCase):
    def test_authenticated_member_has_visible_post_logout_on_desktop_and_mobile(self):
        user = get_user_model().objects.create_user(
            username="logout-member",
            email="logout-member@example.com",
            password="Member-pass-123",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log out", count=2)
        self.assertContains(response, f'action="{reverse("logout")}"', count=2)
        self.assertContains(response, 'method="post"', count=2)
        self.assertContains(response, 'class="logout-form"')
        self.assertContains(response, 'class="mobile-logout-form"')

    def test_authenticated_super_admin_has_same_logout_action(self):
        owner = get_user_model().objects.create_superuser(
            username="logout-owner",
            email="logout-owner@example.com",
            password="Owner-pass-123",
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log out", count=2)

    def test_logout_post_ends_session_and_returns_home(self):
        user = get_user_model().objects.create_user(
            username="logout-post-member",
            password="Member-pass-123",
        )
        self.client.force_login(user)

        response = self.client.post(reverse("logout"), {"next": reverse("home")})

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


class PublicThemeRegressionTests(TestCase):
    def test_home_caches_public_statistics_under_the_read_key(self):
        cache.delete("cca:home:public-stats:v4")

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(cache.get("cca:home:public-stats:v4"))

    def test_home_caches_diverse_featured_dogs(self):
        cache.delete("cca:home:featured-dog-ids:v1")
        kennel = Kennel.objects.create(name="Featured Kennel", slug="featured-kennel")
        first = Dog.objects.create(
            name="Featured First",
            slug="featured-first",
            kennel=kennel,
            is_public=True,
            search_count=50,
        )
        second = Dog.objects.create(
            name="Featured Same Kennel",
            slug="featured-same-kennel",
            kennel=kennel,
            is_public=True,
            search_count=40,
        )
        other = Dog.objects.create(
            name="Featured Other",
            slug="featured-other",
            is_public=True,
            search_count=30,
        )
        for dog in (first, second, other):
            DogImage.objects.create(
                dog=dog,
                image=f"dogs/{dog.slug}.jpg",
                is_primary=True,
            )

        response = self.client.get(reverse("home"))
        names = [dog.name for dog in response.context["featured_dogs"]]

        self.assertIn(first.name, names)
        self.assertIn(other.name, names)
        self.assertNotIn(second.name, names)
        self.assertEqual(
            cache.get("cca:home:featured-dog-ids:v1"),
            [first.pk, other.pk],
        )

    def test_home_falls_back_when_one_kennel_dominates_fast_candidates(self):
        cache.delete("cca:home:featured-dog-ids:v1")
        dominant = Kennel.objects.create(name="Dominant Kennel", slug="dominant-kennel")
        for index in range(96):
            dog = Dog.objects.create(
                name=f"Dominant {index:03d}",
                slug=f"dominant-{index:03d}",
                kennel=dominant,
                is_public=True,
                search_count=1000 - index,
            )
            DogImage.objects.create(
                dog=dog,
                image=f"dogs/{dog.slug}.jpg",
                is_primary=True,
            )

        expected = []
        for index in range(3):
            kennel = Kennel.objects.create(
                name=f"Other Kennel {index}",
                slug=f"other-kennel-{index}",
            )
            dog = Dog.objects.create(
                name=f"Other Featured {index}",
                slug=f"other-featured-{index}",
                kennel=kennel,
                is_public=True,
                search_count=10 - index,
            )
            DogImage.objects.create(
                dog=dog,
                image=f"dogs/{dog.slug}.jpg",
                is_primary=True,
            )
            expected.append(dog.name)

        response = self.client.get(reverse("home"))
        names = [dog.name for dog in response.context["featured_dogs"]]

        self.assertEqual(len(names), 4)
        self.assertTrue(any(name.startswith("Dominant ") for name in names))
        for name in expected:
            self.assertIn(name, names)

    def test_home_uses_simplified_hero_and_current_theme_assets(self):
        response = self.client.get(reverse("home"))

        self.assertNotContains(response, 'class="hero-mark"')
        self.assertNotContains(response, "CANECORSOANCESTRY.COM")
        self.assertContains(response, "hero-mobile-break")
        self.assertContains(response, '<button class="theme-toggle', count=3)
        self.assertContains(response, "Countries")
        self.assertContains(response, "site.css?v=20261007-mobile-upload-v85")
        self.assertContains(response, "premium-polish.css?v=20261007-interaction-v50")


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

    def test_mobile_home_gap_increases_without_moving_header_brand(self):
        css_path = finders.find("core/site.css")
        css = Path(css_path).read_text(encoding="utf-8")

        self.assertIn("padding-top: 96px !important;", css)
        self.assertIn("padding-top: 108px !important;", css)
        self.assertNotIn("iPhone-safe mobile brand position v84", css)
        self.assertNotIn("transform: translateY(7px);", css)
