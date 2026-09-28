import logging
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from registry.models import Dog, DogImage, DogRegistration, HealthRecord, Kennel, Litter

from .seo import json_ld

logger = logging.getLogger(__name__)


def _display_dogs(queryset):
    return queryset.select_related("kennel").prefetch_related(
        Prefetch("images", queryset=DogImage.objects.order_by("-is_primary", "sort_order", "created_at"), to_attr="display_images"),
        Prefetch("registrations", queryset=DogRegistration.objects.select_related("authority"), to_attr="display_registrations"),
    )


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Health check database probe failed")
        response = JsonResponse({"status": "unhealthy"}, status=503)
    else:
        response = JsonResponse({
            "status": "ok",
            "service": "canecorsoancestry",
            "release": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
        })
    response["Cache-Control"] = "no-store"
    return response


def robots_txt(request):
    body = "\n".join([
        "User-agent: *", "Allow: /",
        "Disallow: /member/", "Disallow: /accounts/", "Disallow: /admin/", "Disallow: /dashboard/",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}", "",
    ])
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def home(request):
    featured_dogs = _display_dogs(Dog.objects.filter(is_public=True).order_by("-updated_at"))[:4]
    context = {
        "dog_count": Dog.objects.filter(is_public=True).count(),
        "kennel_count": Kennel.objects.count(),
        "litter_count": Litter.objects.filter(is_public=True).count(),
        "country_count": Dog.objects.filter(is_public=True).exclude(country="").values("country").distinct().count(),
        "featured_dogs": featured_dogs,
        "structured_data": json_ld({
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": settings.SITE_NAME,
            "url": settings.SITE_URL + "/",
            "description": "Cane Corso pedigree, bloodline, kennel and provenance research.",
            "potentialAction": {
                "@type": "SearchAction",
                "target": {"@type": "EntryPoint", "urlTemplate": settings.SITE_URL + "/dogs/?q={search_term_string}"},
                "query-input": "required name=search_term_string",
            },
        }),
    }
    return render(request, "core/home.html", context)


@login_required
def dashboard(request):
    memberships = list(request.user.kennel_memberships.select_related("kennel").order_by("created_at"))
    kennel_ids = [membership.kennel_id for membership in memberships]
    dogs = _display_dogs(Dog.objects.filter(kennel_id__in=kennel_ids).order_by("-updated_at"))[:8]
    litters = Litter.objects.filter(kennel_id__in=kennel_ids).select_related("kennel", "sire", "dam").order_by("-date_of_birth", "code")[:6]
    health_records = HealthRecord.objects.filter(dog__kennel_id__in=kennel_ids).select_related("dog").order_by("-created_at")[:8]
    return render(request, "core/dashboard.html", {
        "memberships": memberships,
        "primary_kennel": memberships[0].kennel if memberships else None,
        "dogs": dogs, "litters": litters, "health_records": health_records,
        "dog_total": Dog.objects.filter(kennel_id__in=kennel_ids).count(),
        "public_dog_total": Dog.objects.filter(kennel_id__in=kennel_ids, is_public=True).count(),
        "litter_total": Litter.objects.filter(kennel_id__in=kennel_ids).count(),
    })
