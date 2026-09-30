from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, F, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.seo import json_ld

from pedigrees.services import direct_relative_health, mate_relationships, offspring_for, sibling_relationships

from .models import (
    Dog,
    DogDocument,
    DogImage,
    DogRedirect,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    Kennel,
    Litter,
    Submission,
)
from .permissions import can_contribute_to_dog


def _dog_cards(queryset):
    return queryset.select_related("kennel", "sire", "dam").prefetch_related(
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


def dog_search(request):
    query = request.GET.get("q", "").strip()
    sex = request.GET.get("sex", "").strip()
    country = request.GET.get("country", "").strip()
    kennel_slug = request.GET.get("kennel", "").strip()
    exact = request.GET.get("exact") == "1"

    dogs = _dog_cards(Dog.objects.filter(is_public=True))
    if query:
        if exact:
            dogs = dogs.filter(
                Q(name__iexact=query)
                | Q(aliases__name__iexact=query)
                | Q(registrations__number__iexact=query)
            ).distinct()
        else:
            dogs = dogs.filter(
                Q(name__icontains=query)
                | Q(bloodline__icontains=query)
                | Q(aliases__name__icontains=query)
                | Q(registrations__number__icontains=query)
                | Q(kennel__name__icontains=query)
            ).distinct()
    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE, Dog.Sex.UNKNOWN}:
        dogs = dogs.filter(sex=sex)
    if country:
        dogs = dogs.filter(country__iexact=country)
    if kennel_slug:
        dogs = dogs.filter(kennel__slug=kennel_slug)

    dogs = dogs.order_by("name")
    paginator = Paginator(dogs, 24)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    countries = (
        Dog.objects.filter(is_public=True)
        .exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )
    kennels = Kennel.objects.order_by("name")

    return render(
        request,
        "registry/dog_search.html",
        {
            "dogs": page_obj.object_list,
            "page_obj": page_obj,
            "result_count": paginator.count,
            "querystring": query_params.urlencode(),
            "query": query,
            "exact": exact,
            "sex": sex,
            "country": country,
            "kennel_slug": kennel_slug,
            "countries": countries,
            "kennels": kennels,
        },
    )


def dog_detail(request, slug):
    dogs = _dog_cards(Dog.objects.filter(is_public=True)).prefetch_related(
        Prefetch(
            "health_records",
            queryset=HealthRecord.objects.order_by("test_type", "-tested_on"),
            to_attr="display_health_records",
        ),
        Prefetch(
            "sources",
            queryset=DogSource.objects.order_by("-verified_at", "-created_at"),
            to_attr="display_sources",
        ),
        Prefetch(
            "titles",
            queryset=DogTitle.objects.order_by("name"),
            to_attr="display_titles",
        ),
        Prefetch(
            "documents",
            queryset=DogDocument.objects.filter(is_public=True).order_by("-created_at"),
            to_attr="display_documents",
        ),
    )
    dog = dogs.filter(slug=slug).first()
    if dog is None:
        old = DogRedirect.objects.select_related("dog").filter(old_slug=slug).first()
        if old and old.dog.is_public:
            return redirect("registry:dog-detail", slug=old.dog.slug, permanent=True)
        return get_object_or_404(dogs, slug=slug)

    if request.GET.get("source") == "search":
        Dog.objects.filter(pk=dog.pk).update(search_count=F("search_count") + 1)

    image_url = dog.display_images[0].image.url if dog.display_images else None
    structured_data = {
        "@context": "https://schema.org",
        "@type": "Thing",
        "name": dog.name,
        "url": f"{settings.SITE_URL}{request.path}",
        "description": dog.bio or f"Cane Corso pedigree and ancestry record for {dog.name}.",
        "identifier": [registration.number for registration in dog.display_registrations],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "Sex", "value": dog.get_sex_display()},
            {"@type": "PropertyValue", "name": "Colour", "value": dog.colour or "Not recorded"},
            {"@type": "PropertyValue", "name": "Country", "value": dog.country or "Not recorded"},
            {"@type": "PropertyValue", "name": "Verification", "value": dog.get_verification_state_display()},
        ],
    }
    if dog.date_of_birth:
        structured_data["birthDate"] = dog.date_of_birth.isoformat()
    if image_url:
        structured_data["image"] = image_url
    if dog.kennel:
        structured_data["isPartOf"] = {
            "@type": "Organization",
            "name": dog.kennel.name,
            "url": f"{settings.SITE_URL}" + reverse("registry:kennel-detail", args=[dog.kennel.slug]),
        }

    return render(
        request,
        "registry/dog_detail.html",
        {
            "dog": dog,
            "siblings": sibling_relationships(dog),
            "offspring": offspring_for(dog),
            "mates": mate_relationships(dog),
            "relative_health": direct_relative_health(dog),
            "can_contribute": can_contribute_to_dog(request.user, dog),
            "structured_data": json_ld(structured_data),
        },
    )


def pedigree_statistics(request):
    top_sires = (
        _dog_cards(
            Dog.objects.filter(is_public=True, sex=Dog.Sex.MALE).annotate(
                public_offspring_count=Count(
                    "sired_offspring",
                    filter=Q(sired_offspring__is_public=True),
                    distinct=True,
                )
            )
        )
        .filter(public_offspring_count__gt=0)
        .order_by("-public_offspring_count", "name")[:20]
    )
    top_dams = (
        _dog_cards(
            Dog.objects.filter(is_public=True, sex=Dog.Sex.FEMALE).annotate(
                public_offspring_count=Count(
                    "dammed_offspring",
                    filter=Q(dammed_offspring__is_public=True),
                    distinct=True,
                )
            )
        )
        .filter(public_offspring_count__gt=0)
        .order_by("-public_offspring_count", "name")[:20]
    )
    top_kennels = (
        Kennel.objects.annotate(
            public_dog_count=Count(
                "dogs", filter=Q(dogs__is_public=True), distinct=True
            )
        )
        .filter(public_dog_count__gt=0)
        .order_by("-public_dog_count", "name")[:20]
    )
    return render(
        request,
        "registry/statistics.html",
        {
            "top_sires": top_sires,
            "top_dams": top_dams,
            "top_kennels": top_kennels,
        },
    )


def kennel_list(request):
    kennels = (
        Kennel.objects.annotate(
            public_dog_count=Count("dogs", filter=Q(dogs__is_public=True), distinct=True),
            public_litter_count=Count(
                "litters", filter=Q(litters__is_public=True), distinct=True
            ),
        )
        .order_by("name")
    )
    page_obj = Paginator(kennels, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "registry/kennel_list.html",
        {"kennels": page_obj.object_list, "page_obj": page_obj},
    )


def kennel_detail(request, slug):
    kennel = get_object_or_404(Kennel, slug=slug)
    dog_queryset = _dog_cards(
        Dog.objects.filter(kennel=kennel, is_public=True)
    ).order_by("name")
    litter_queryset = (
        Litter.objects.filter(kennel=kennel, is_public=True)
        .select_related("sire", "dam")
        .order_by("-date_of_birth", "code")
    )
    dog_page = Paginator(dog_queryset, 24).get_page(request.GET.get("dogs_page"))
    litter_page = Paginator(litter_queryset, 20).get_page(request.GET.get("litters_page"))
    kennel_linked = kennel.memberships.exists()
    is_member = bool(
        request.user.is_authenticated
        and request.user.kennel_memberships.filter(kennel=kennel).exists()
    )
    pending_claim = Submission.objects.filter(
        kind=Submission.Kind.KENNEL_CLAIM,
        status=Submission.Status.PENDING,
        kennel=kennel,
    ).select_related("submitted_by").first()
    claim_pending = bool(
        request.user.is_authenticated
        and pending_claim
        and pending_claim.submitted_by_id == request.user.id
    )
    claim_in_review = pending_claim is not None
    return render(
        request,
        "registry/kennel_detail.html",
        {
            "kennel": kennel,
            "dogs": dog_page.object_list,
            "litters": litter_page.object_list,
            "dog_page": dog_page,
            "litter_page": litter_page,
            "dog_total": dog_page.paginator.count,
            "litter_total": litter_page.paginator.count,
            "can_claim": (
                request.user.is_authenticated
                and not kennel_linked
                and not is_member
                and not claim_in_review
            ),
            "claim_pending": claim_pending,
            "claim_in_review": claim_in_review,
        },
    )


def litter_detail(request, pk):
    litter = get_object_or_404(
        Litter.objects.select_related("kennel", "sire", "dam"),
        pk=pk,
        is_public=True,
    )
    offspring = _dog_cards(
        Dog.objects.filter(litter=litter, is_public=True)
    ).order_by("name")
    return render(
        request,
        "registry/litter_detail.html",
        {"litter": litter, "offspring": offspring},
    )
