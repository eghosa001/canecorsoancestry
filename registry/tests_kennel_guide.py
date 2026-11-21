"""Focused checks for the unbiased Nigeria / Africa kennel SEO guide."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from registry.models import Kennel


@override_settings(SITE_URL="https://canecorsoancestry.com")
class NigeriaKennelGuideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Kennel.objects.create(
            name="Alpha Cane Corso", slug="alpha-cane-corso",
            is_public=True, country="Nigeria",
        )
        cls.bellissimo = Kennel.objects.create(
            name="Bellissimo Geni", slug="bellissimo-geni",
            is_public=True, city="Benin City", country="Nigeria",
            verified_at=timezone.now(),
            description="Documented Cane Corso ancestry and breeding records.",
        )
        cls.italian = Kennel.objects.create(
            name="Italian Kennel", slug="italian-kennel",
            is_public=True, country="Italy",
        )
        cls.archived = Kennel.objects.create(
            name="Archived Kennel", slug="archived-kennel",
            is_public=True, country="Nigeria", is_archive_hypothesis=True,
        )
        cls.private = Kennel.objects.create(
            name="Private Kennel", slug="private-kennel",
            is_public=False, country="Nigeria",
        )

    def test_guide_is_public_neutral_and_lists_only_nigerian_records(self):
        response = self.client.get(reverse("registry:kennel-nigeria-guide"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "best Cane Corso kennel in Nigeria")
        self.assertContains(response, "application/ld+json")
        names = [x.name for x in response.context["kennels"]]
        self.assertEqual(names, ["Alpha Cane Corso", "Bellissimo Geni"])
        self.assertNotContains(response, "Italian Kennel")
        self.assertNotContains(response, "Archived Kennel")
        self.assertNotContains(response, "Private Kennel")

    def test_directory_and_local_profile_link_to_guide(self):
        guide = reverse("registry:kennel-nigeria-guide")
        listing = self.client.get(reverse("registry:kennel-list"))
        self.assertContains(listing, guide)
        local = self.client.get(
            reverse("registry:kennel-detail", args=[self.bellissimo.slug])
        )
        self.assertContains(local, guide)
        foreign = self.client.get(
            reverse("registry:kennel-detail", args=[self.italian.slug])
        )
        self.assertNotContains(foreign, guide)

    def test_guide_is_in_public_sitemap(self):
        from core.sitemaps import StaticViewSitemap
        self.assertIn("registry:kennel-nigeria-guide", StaticViewSitemap().items())
