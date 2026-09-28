from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import render

from registry.models import Dog, DogImage, DogRegistration, HealthRecord, Kennel, Litter


def _display_dogs(queryset):
    return queryset.select_related("kennel").prefetch_related(
        Prefetch(
            "images",
            queryset=DogImage.objects.order_by("-is_primary", "sort_order", "created_at"),
            to_attr="display_images",
        ),
        Prefetch(
            "registrations",
            queryset=DogRegistration.objects.select_related("authority"),
            to_attr="display_registrations",
        ),
    )


def home(request):
    featured_dogs = _display_dogs(
        Dog.objects.filter(is_public=True).order_by("-updated_at")
    )[:4]
    context = {
        "dog_count": Dog.objects.filter(is_public=True).count(),
        "kennel_count": Kennel.objects.count(),
        "litter_count": Litter.objects.filter(is_public=True).count(),
        "country_count": (
            Dog.objects.filter(is_public=True)
            .exclude(country="")
            .values("country")
            .distinct()
            .count()
        ),
        "featured_dogs": featured_dogs,
    }
    return render(request, "core/home.html", context)


@login_required
def dashboard(request):
    memberships = list(
        request.user.kennel_memberships.select_related("kennel").order_by("created_at")
    )
    kennel_ids = [membership.kennel_id for membership in memberships]

    dogs = _display_dogs(
        Dog.objects.filter(kennel_id__in=kennel_ids).order_by("-updated_at")
    )[:8]
    litters = (
        Litter.objects.filter(kennel_id__in=kennel_ids)
        .select_related("kennel", "sire", "dam")
        .order_by("-date_of_birth", "code")[:6]
    )
    health_records = (
        HealthRecord.objects.filter(dog__kennel_id__in=kennel_ids)
        .select_related("dog")
        .order_by("-created_at")[:8]
    )

    context = {
        "memberships": memberships,
        "primary_kennel": memberships[0].kennel if memberships else None,
        "dogs": dogs,
        "litters": litters,
        "health_records": health_records,
        "dog_total": Dog.objects.filter(kennel_id__in=kennel_ids).count(),
        "public_dog_total": Dog.objects.filter(
            kennel_id__in=kennel_ids, is_public=True
        ).count(),
        "litter_total": Litter.objects.filter(kennel_id__in=kennel_ids).count(),
    }
    return render(request, "core/dashboard.html", context)
