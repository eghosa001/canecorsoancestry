from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import DatabaseError, connection, transaction
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
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
    public_verification_label,
)
from .permissions import can_contribute_to_dog
from .querysets import one_dog_per_kennel, public_dog_match_filter, with_stored_images


PROFILE_RELATION_PREVIEW_LIMIT = 18
SEARCH_HIT_THROTTLE_SECONDS = 30


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


def _attach_source_images_for_missing(dogs):
    """Load source-image metadata only for cards that do not already have stored media."""
    missing = [dog for dog in dogs if not getattr(dog, "display_images", [])]
    if not missing:
        _attach_source_image_urls(dogs)
        return

    by_dog = {}
    sources = (
        DogSource.objects.filter(dog_id__in=[dog.pk for dog in missing])
        .only("dog_id", "raw_payload", "verified_at", "created_at")
        .order_by("dog_id", "-verified_at", "-created_at")
    )
    for source in sources:
        by_dog.setdefault(source.dog_id, []).append(source)
    for dog in missing:
        dog.display_source_media = by_dog.get(dog.pk, [])
    _attach_source_image_urls(dogs)


def dog_suggestions(request):
    query = request.GET.get("q", "").strip()
    sex = request.GET.get("sex", "").strip()
    browse = request.GET.get("browse") == "1"

    dogs = Dog.objects.filter(is_public=True)

    if len(query) >= 3:
        dogs = dogs.filter(public_dog_match_filter(query))
    elif query:
        dogs = dogs.filter(name__istartswith=query)
    elif not browse:
        return JsonResponse({"results": []})

    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE}:
        dogs = dogs.filter(Q(sex=sex) | Q(sex=Dog.Sex.UNKNOWN))

    registration_number = (
        DogRegistration.objects.filter(dog_id=OuterRef("pk"))
        .order_by("id")
        .values("number")[:1]
    )
    # Keep an empty browse picker compact, but give typed searches enough
    # room for duplicate names, kennels and registration variants.
    suggestion_limit = 8 if browse and not query else 16
    rows = list(
        dogs.annotate(_registration=Subquery(registration_number))
        .values(
            "id",
            "name",
            "slug",
            "sex",
            "kennel__name",
            "_registration",
        )
        .order_by("-search_count", "-updated_at", "name")[:suggestion_limit]
    )
    sex_labels = dict(Dog.Sex.choices)
    results = [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "slug": row["slug"],
            "sex": sex_labels.get(row["sex"], row["sex"]),
            "kennel": row["kennel__name"] or "",
            "registration": row["_registration"] or "",
        }
        for row in rows
    ]
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
    dogs = _dog_cards(base_dogs, include_sources=False)
    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE, Dog.Sex.UNKNOWN}:
        dogs = dogs.filter(sex=sex)
    if country:
        dogs = dogs.filter(country__iexact=country)
    if kennel_slug:
        dogs = dogs.filter(kennel__slug=kennel_slug)

    if not query and not kennel_slug:
        dogs = one_dog_per_kennel(dogs)

    dogs = dogs.order_by("name") if query else dogs.order_by("-search_count", "-updated_at", "name")
    paginator = Paginator(dogs, 18)
    if not query and not sex and not country and not kennel_slug:
        cached_count = cache.get("cca:dog-search:default-count:v1")
        if cached_count is None:
            cached_count = paginator.count
            cache.set("cca:dog-search:default-count:v1", cached_count, 900)
        paginator.__dict__["count"] = cached_count
    page_obj = paginator.get_page(request.GET.get("page"))
    _attach_source_images_for_missing(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)

    countries = cache.get("cca:dog-search:countries:v2")
    if countries is None:
        countries = list(
            Dog.objects.filter(is_public=True)
            .exclude(country="")
            .values_list("country", flat=True)
            .distinct()
            .order_by("country")
        )
        cache.set("cca:dog-search:countries:v2", countries, 900)

    kennels = cache.get("cca:dog-search:kennels:v2")
    if kennels is None:
        kennels = list(Kennel.objects.order_by("name").values("name", "slug"))
        cache.set("cca:dog-search:kennels:v2", kennels, 900)

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


def _record_search_hit_without_wait(dog_id):
    """Keep popularity useful without allowing telemetry to slow navigation."""
    throttle_key = f"cca:dog-search-hit:{dog_id}"
    if not cache.add(throttle_key, 1, SEARCH_HIT_THROTTLE_SECONDS):
        return

    if connection.vendor != "postgresql":
        Dog.objects.filter(pk=dog_id).update(search_count=F("search_count") + 1)
        return

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '100ms'")
                cursor.execute("SET LOCAL statement_timeout = '200ms'")
            Dog.objects.filter(pk=dog_id).update(search_count=F("search_count") + 1)
    except DatabaseError:
        # Search popularity is best-effort telemetry. The throttle deliberately
        # remains in place after a timeout so a hot profile cannot create a
        # retry storm while the database is under pressure.
        return


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
        _record_search_hit_without_wait(dog.pk)

    image_url = (
        dog.display_images[0].image.url
        if dog.display_images
        else (dog.source_image_url or None)
    )
    structured_data = {
        "@context": "https://schema.org",
        "@type": "Thing",
        "name": dog.name,
        "url": request.build_absolute_uri(request.path),
        "description": dog.bio or f"Cane Corso pedigree and ancestry record for {dog.name}.",
        "identifier": [registration.number for registration in dog.display_registrations],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "Sex", "value": dog.get_sex_display()},
            {"@type": "PropertyValue", "name": "Colour", "value": dog.colour or "Not recorded"},
            {"@type": "PropertyValue", "name": "Country", "value": dog.country or "Not recorded"},
            {"@type": "PropertyValue", "name": "Verification", "value": public_verification_label(dog.verification_state)},
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
            "url": request.build_absolute_uri(reverse("registry:kennel-detail", args=[dog.kennel.slug])),
        }

    relation_limit = PROFILE_RELATION_PREVIEW_LIMIT
    sibling_rows = sibling_relationships(dog, limit=relation_limit + 1)
    siblings_truncated = len(sibling_rows) > relation_limit
    siblings = sibling_rows[:relation_limit]

    offspring_queryset = offspring_for(dog)
    offspring_rows = list(offspring_queryset[: relation_limit + 1])
    offspring_truncated = len(offspring_rows) > relation_limit
    offspring = offspring_rows[:relation_limit]

    mate_rows = mate_relationships(
        dog,
        children=offspring_rows,
        exact_counts=offspring_truncated,
    )
    mates_truncated = len(mate_rows) > relation_limit
    mates = mate_rows[:relation_limit]

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
            "siblings_truncated": siblings_truncated,
            "offspring": offspring,
            "offspring_truncated": offspring_truncated,
            "mates": mates,
            "mates_truncated": mates_truncated,
            "relative_health": relative_health,
            "coi_percent": coi_percent,
            "coi_error": coi_error,
            "relation_limit": relation_limit,
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
    query = request.GET.get("q", "").strip()
    public_dog_count = (
        Dog.objects.filter(kennel_id=OuterRef("pk"), is_public=True)
        .values("kennel_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    public_litter_count = (
        Litter.objects.filter(kennel_id=OuterRef("pk"), is_public=True)
        .values("kennel_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    kennels = Kennel.objects.annotate(
        public_dog_count=Coalesce(
            Subquery(public_dog_count, output_field=IntegerField()),
            Value(0),
        ),
        public_litter_count=Coalesce(
            Subquery(public_litter_count, output_field=IntegerField()),
            Value(0),
        ),
    )
    if query:
        kennels = kennels.filter(
            Q(name__icontains=query)
            | Q(city__icontains=query)
            | Q(country__icontains=query)
        )
    kennels = kennels.order_by("name")

    paginator = Paginator(kennels, 18)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    return render(
        request,
        "registry/kennel_list.html",
        {
            "kennels": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "querystring": query_params.urlencode(),
            "result_count": paginator.count,
        },
    )


def kennel_detail(request, slug):
    kennel = get_object_or_404(Kennel, slug=slug)
    public_dogs = Dog.objects.filter(kennel=kennel, is_public=True)
    public_dog_total = public_dogs.count()
    stored_image_ids = DogImage.objects.order_by().values("dog_id").distinct()
    source_image_ids = (
        DogSource.objects.filter(
            Q(raw_payload__image_url__startswith="https://www.canecorsopedigree.com/static/images/animal/")
            | Q(raw_payload__image_url__startswith="https://canecorsopedigree.com/static/images/animal/")
        )
        .order_by()
        .values("dog_id")
        .distinct()
    )
    dog_queryset = _dog_cards(
        public_dogs.filter(
            Q(pk__in=Subquery(stored_image_ids))
            | Q(pk__in=Subquery(source_image_ids))
        ),
        include_sources=False,
    ).order_by("name")
    litter_queryset = (
        Litter.objects.filter(kennel=kennel, is_public=True)
        .select_related("sire", "dam")
        .order_by("-date_of_birth", "code")
    )
    dog_page = Paginator(dog_queryset, 24).get_page(request.GET.get("dogs_page"))
    _attach_source_images_for_missing(dog_page.object_list)
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
            "public_dog_total": public_dog_total,
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
    offspring = list(
        _dog_cards(
            Dog.objects.filter(litter=litter, is_public=True)
        ).order_by("name")
    )
    _attach_source_image_urls(offspring)
    imaged_offspring = [
        dog
        for dog in offspring
        if getattr(dog, "display_images", []) or getattr(dog, "source_image_url", "")
    ]
    other_offspring = [
        dog
        for dog in offspring
        if not getattr(dog, "display_images", []) and not getattr(dog, "source_image_url", "")
    ]
    return render(
        request,
        "registry/litter_detail.html",
        {
            "litter": litter,
            "offspring_total": len(offspring),
            "imaged_offspring": imaged_offspring,
            "other_offspring": other_offspring,
        },
    )
