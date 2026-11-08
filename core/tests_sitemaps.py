"""Sitemap regressions: deterministic paging and strict public visibility."""
from django.test import TestCase

from core.sitemaps import DogSitemap, KennelSitemap, LitterSitemap
from registry.models import Dog, Kennel


class PublicSitemapSafetyTests(TestCase):
    def test_dog_sitemap_is_stably_ordered_with_duplicate_names(self):
        a = Dog.objects.create(name="Same Dog Name", slug="same-dog-one", is_public=True)
        b = Dog.objects.create(name="Same Dog Name", slug="same-dog-two", is_public=True)
        Dog.objects.create(name="Private Dog", slug="private-sitemap", is_public=False)
        Dog.objects.create(
            name="Hidden by Review", slug="moderation-hidden-sitemap",
            is_public=True, hidden_by_moderation=True,
        )
        locked_kennel = Kennel.objects.create(
            name="Hidden Breeder", slug="hidden-breeder", hide_dogs=True
        )
        Dog.objects.create(
            name="Kennel Hidden", slug="kennel-hidden-sitemap",
            kennel=locked_kennel, is_public=True,
        )
        items = DogSitemap().items()
        self.assertEqual(items.query.order_by, ("name", "pk"))
        self.assertEqual(set(items.values_list("slug", flat=True)), {a.slug, b.slug})
        self.assertEqual(
            list(items.values_list("pk", flat=True)),
            sorted((a.pk, b.pk)),
        )

    def test_kennel_and_litter_sitemaps_have_stable_sort_keys(self):
        self.assertEqual(KennelSitemap().items().query.order_by, ("name", "pk"))
        self.assertEqual(LitterSitemap().items().query.order_by, ("-created_at", "pk"))

    def test_sitemap_xml_excludes_unpublished_and_hidden_dogs(self):
        Dog.objects.create(name="Published Sitemap", slug="published-sitemap", is_public=True)
        Dog.objects.create(name="Private Sitemap", slug="private-sitemap", is_public=False)
        Dog.objects.create(
            name="Hidden Sitemap", slug="hidden-sitemap",
            is_public=True, hidden_by_moderation=True,
        )
        response = self.client.get("/sitemap-dogs.xml")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("/dogs/published-sitemap/", body)
        self.assertNotIn("/dogs/private-sitemap/", body)
        self.assertNotIn("/dogs/hidden-sitemap/", body)
