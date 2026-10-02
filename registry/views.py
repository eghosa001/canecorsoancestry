from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import urlparse

from core.seo import json_ld

from pedigrees.services import (
    PedigreeCycleError,
    direct_relative_health,
    inbreeding_coefficient,
    mate_relationships,
    offspring_for,
    sibling_relationships,
)

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
from .querysets import one_dog_per_kennel, public_dog_match_filter, with_stored_images


def _dog_cards(queryset, *, include_parents=False, include_sources=True):
    related = ["kennel"]
    if include_parents:
        related.extend(["sire", "dam"])

    queryset = queryset.select_related(*related).prefetch_related(
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
    if include_sources:
        queryset = queryset.prefetch_related(
            Prefetch(
                "sources",
                queryset=DogSource.objects.order_by("-verified_at", "-created_at"),
                to_attr="display_source_media",
            )
        )
    return queryset


def _source_image_url(sources):
    for source in sources:
        payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
        image_url = str(payload.get("image_url") or "").strip()
        if not image_url:
            continue
        parsed = urlparse(image_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"canecorsopedigree.com", "www.canecorsopedigree.com"}
            and parsed.path.startswith("/static/images/animal/")
        ):
            return image_url
    return ""


def _attach_source_image_urls(dogs):
    for dog in dogs:
        dog.source_image_url = ""
        if not getattr(dog, "display_images", []):
            dog.source_image_url = _source_image_url(
                getattr(dog, "display_source_media", [])
            )


def _public_dogs_with_images():
    return with_stored_images(Dog.objects.filter(is_public=True))


def dog_suggestions(request):
    query = request.GET.get("q", "").strip()
    sex = request.GET.get("sex", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    dogs = Dog.objects.filter(is_public=True).filter(
        public_dog_match_filter(query)
    )
    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE}:
        dogs = dogs.filter(Q(sex=sex) | Q(sex=Dog.Sex.UNKNOWN))

    dogs = (
        dogs.select_related("kennel")
        .prefetch_related("registrations")
        .order_by("-search_count", "name")[:8]
    )
    results = []
    for dog in dogs:
        registration = next(iter(dog.registrations.all()), None)
        results.append(
            {
                "id": str(dog.pk),
                "name": dog.name,
                "slug": dog.slug,
                "sex": dog.get_sex_display(),
                "kennel": dog.kennel.name if dog.kennel_id else "",
                "registration": registration.number if registration else "",
            }
        )
    response = JsonResponse({"results": results})
    response["Cache-Control"] = "public, max-age=30, stale-while-revalidate=120"
    return response


def dog_search(request):
    query = request.GET.get("q", "").strip()
    sex = request.GET.get("sex", "").strip()
    country = request.GET.get("country", "").strip()
    kennel_slug = request.GET.get("kennel", "").strip()
    exact = request.GET.get("exact") == "1"

    if query:
        base_dogs = Dog.objects.filter(is_public=True).filter(
            public_dog_match_filter(query, exact=exact)
        )
    else:
        base_dogs = _public_dogs_with_images()
    dogs = _dog_cards(base_dogs, include_sources=bool(query))
    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE, Dog.Sex.UNKNOWN}:
        dogs = dogs.filter(sex=sex)
    if country:
        dogs = dogs.filter(country__iexact=country)
    if kennel_slug:
        dogs = dogs.filter(kennel__slug=kennel_slug)

    if not query and not kennel_slug:
        dogs = one_dog_per_kennel(dogs)

    dogs = dogs.order_by("name") if query else dogs.order_by("-search_count", "-updated_at", "name")
    paginator = Paginator(dogs, 24)
    if not query and not sex and not country and not kennel_slug:
        cached_count = cache.get("cca:dog-search:default-count:v1")
        if cached_count is None:
            cached_count = paginator.count
            cache.set("cca:dog-search:default-count:v1", cached_count, 900)
        paginator.__dict__["count"] = cached_count
    page_obj = paginator.get_page(request.GET.get("page"))
    _attach_source_image_urls(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)

    countries = cache.get("cca:dog-search:countries:v1")
    if countries is None:
        countries = list(
            Dog.objects.filter(is_public=True)
            .exclude(country="")
            .values_list("country", flat=True)
            .distinct()
            .order_by("country")
        )
        cache.set("cca:dog-search:countries:v1", countries, 900)

    kennels = cache.get("cca:dog-search:kennels:v1")
    if kennels is None:
        kennels = list(Kennel.objects.order_by("name").values("name", "slug"))
        cache.set("cca:dog-search:kennels:v1", kennels, 900)

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
    dogs = _dog_cards(
        Dog.objects.filter(is_public=True),
        include_parents=True,
        include_sources=False,
    ).prefetch_related(
        Prefetch(
            "health_records",
            queryset=HealthRecord.objects.order_by("test_type", "-tested_on"),
            to_attr="display_health_records",
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

    if not dog.display_images:
        dog.display_source_media = list(
            DogSource.objects.filter(dog=dog).order_by("-verified_at", "-created_at")
        )
    _attach_source_image_urls([dog])

    try:
        coi_percent = inbreeding_coefficient(dog, public_only=True) * 100
        coi_error = ""
    except PedigreeCycleError:
        coi_percent = None
        coi_error = "Pedigree cycle detected"

    if request.GET.get("source") == "search":
        Dog.objects.filter(pk=dog.pk).update(search_count=F("search_count") + 1)

    image_url = (
        dog.display_images[0].image.url
        if dog.display_images
        else (dog.source_image_url or None)
    )
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

    siblings = sibling_relationships(dog)
    offspring = list(offspring_for(dog))
    mates = mate_relationships(dog, children=offspring)
    relative_health = direct_relative_health(
        dog,
        sibling_rows=siblings,
        children=offspring,
    )

    return render(
        request,
        "registry/dog_detail.html",
        {
            "dog": dog,
            "siblings": siblings,
            "offspring": offspring,
            "mates": mates,
            "relative_health": relative_health,
            "coi_percent": coi_percent,
            "coi_error": coi_error,
            "can_contribute": can_contribute_to_dog(request.user, dog),
            "structured_data": json_ld(structured_data),
        },
    )


def _top_public_parents(parent_field, sex):
    relation = parent_field.removesuffix("_id")
    rows = list(
        Dog.objects.filter(
            is_public=True,
            **{
                f"{relation}__is_public": True,
                f"{relation}__sex": sex,
            },
        )
        .values(parent_field)
        .annotate(public_offspring_count=Count("id"))
        .order_by("-public_offspring_count")[:20]
    )
    parent_ids = [row[parent_field] for row in rows]
    parents = Dog.objects.filter(
        pk__in=parent_ids,
        is_public=True,
        sex=sex,
    ).in_bulk()
    ranked = []
    for row in rows:
        parent = parents.get(row[parent_field])
        if parent is None:
            continue
        parent.public_offspring_count = row["public_offspring_count"]
        ranked.append(parent)
    ranked.sort(key=lambda dog: (-dog.public_offspring_count, dog.name.lower()))
    return ranked[:20]


def pedigree_statistics(request):
    top_sires = _top_public_parents("sire_id", Dog.Sex.MALE)
    top_dams = _top_public_parents("dam_id", Dog.Sex.FEMALE)
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
    _attach_source_image_urls(dog_page.object_list)
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
