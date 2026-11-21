"""Editorial, evidence-based guidance and geographic kennel discovery pages."""
from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse

from core.seo import json_ld
from registry.models import Kennel


def nigeria_kennel_guide(request):
    """A neutral guide, not a paid list or a claim of independent rankings."""
    kennels = list(
        Kennel.objects.filter(is_public=True, is_archive_hypothesis=False)
        .filter(Q(country__iexact="Nigeria") | Q(country__iexact="NG"))
        .only("name", "slug", "city", "country", "description", "verified_at")
        .order_by("name", "pk")
    )
    path = reverse("registry:kennel-nigeria-guide")
    return render(request, "registry/kennel_nigeria_guide.html", {
        "kennels": kennels,
        "structured_data": json_ld({
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": "Choosing a Cane Corso Kennel in Nigeria and Africa",
            "description": (
                "Compare Cane Corso kennels using documented pedigrees, "
                "health screening, welfare practices and transparent breeder information."
            ),
            "url": f"{settings.SITE_URL}{path}",
            "about": {"@type": "Thing", "name": "Cane Corso dog breeders in Nigeria"},
        }),
    })
