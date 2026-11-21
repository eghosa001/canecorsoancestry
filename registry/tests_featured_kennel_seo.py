"""Targeted SEO and editorial featured-kennel checks."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from registry.models import Kennel


@override_settings(
    SITE_URL="https://canecorsoancestry.com",
    CCA_FEATURED_KENNEL_NAME="Bellissimo Geni",
)
class FeaturedKennelSEOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ordinary = Kennel.objects.create(
            name="Alpha Kennel", slug="alpha-kennel", is_public=True
        )
        cls.featured = Kennel.objects.create(
            name="Bellissimo Geni",
            slug="bellissimo-geni",
            is_public=True,
            verified_at=timezone.now(),
            city="Benin City",
            country="Nigeria",
            description="A kennel profile backed by reviewed records.",
        )
        cls.unverified = Kennel.objects.create(
            name="Bellissimo Geni Archives",
            slug="bellissimo-geni-archives",
            is_public=True,
            is_archive_hypothesis=True,
        )

    def test_featured_verified_kennel_precedes_alphabetical_directory(self):
        response = self.client.get(reverse("registry:kennel-list"))
        self.assertEqual(response.status_code, 200)
        kennels = list(response.context["kennels"])
        self.assertEqual(kennels[0].pk, self.featured.pk)
        self.assertEqual(kennels[0].is_featured, 1)
        self.assertContains(response, "Featured kennel")
        self.assertContains(response, "Cane Corso Kennel Directory")

    def test_search_results_are_unbiased(self):
        response = self.client.get(reverse("registry:kennel-list"), {"q": "Kennel"})
        kennels = list(response.context["kennels"])
        self.assertEqual(kennels[0].pk, self.ordinary.pk)

    def test_kennel_profile_has_unique_seo_and_provenance(self):
        response = self.client.get(reverse("registry:kennel-detail", args=[self.featured.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bellissimo Geni · Cane Corso Kennel &amp; Pedigrees")
        self.assertContains(response, "application/ld+json")
        self.assertContains(response, "A kennel profile backed by reviewed records.")
        self.assertContains(response, "site-owner selection")

    def test_featured_kennel_link_on_home(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("registry:kennel-detail", args=[self.featured.slug]))
        self.assertContains(response, "Site-owner selection")
