from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from registry.models import Dog, Kennel, Litter


class StaticViewSitemap(Sitemap):
    priority = 0.6
    changefreq = "weekly"
    def items(self):
        return ("home", "registry:dog-search", "registry:kennel-list", "pedigrees:index", "pedigrees:virtual-mating")
    def location(self, item):
        return reverse(item)


class DogSitemap(Sitemap):
    priority = 0.9
    changefreq = "weekly"
    def items(self):
        return Dog.objects.filter(is_public=True).only("slug", "updated_at").order_by("name")
    def location(self, dog):
        return reverse("registry:dog-detail", args=[dog.slug])
    def lastmod(self, dog):
        return dog.updated_at


class PedigreeSitemap(DogSitemap):
    priority = 0.7
    def location(self, dog):
        return reverse("pedigrees:detail", args=[dog.slug])


class KennelSitemap(Sitemap):
    priority = 0.7
    changefreq = "weekly"
    def items(self):
        return Kennel.objects.only("slug", "updated_at").order_by("name")
    def location(self, kennel):
        return reverse("registry:kennel-detail", args=[kennel.slug])
    def lastmod(self, kennel):
        return kennel.updated_at


class LitterSitemap(Sitemap):
    priority = 0.5
    changefreq = "monthly"
    def items(self):
        return Litter.objects.filter(is_public=True).only("pk", "created_at").order_by("-created_at")
    def location(self, litter):
        return reverse("registry:litter-detail", args=[litter.pk])
    def lastmod(self, litter):
        return litter.created_at


SITEMAPS = {
    "static": StaticViewSitemap,
    "dogs": DogSitemap,
    "pedigrees": PedigreeSitemap,
    "kennels": KennelSitemap,
    "litters": LitterSitemap,
}
