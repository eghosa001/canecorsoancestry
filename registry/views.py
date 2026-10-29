from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import DatabaseError, connection, transaction
from django.db.models import Case, Count, Exists, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import urlparse
import re

from core.seo import json_ld

from pedigrees.services import (
    COI_GENERATION_CHOICES,
    requested_coi_generations,
    direct_relative_health,
    public_profile_coi,
    mate_relationships,
    offspring_for,
    profile_direct_relations,
    sibling_relationships,
)

from .models import (
    BreedDNAReport,
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
    VerificationState,
    VerificationEvent,
    public_verification_label,
)
from .permissions import can_access_public_pedigree_analysis, can_contribute_to_dog
from .genetic_health import MARKER_CODES, SCREENING_RESULTS, marker_status_rows, readable_health_result, unstructured_breed_claim
from .orthopaedic_health import describe_orthopaedic_result
from .legacy_health import legacy_mixed_health_rows
from .dna import percentage_text
from .querysets import one_dog_per_kennel, public_dog_match_filter, with_card_image, with_card_registration, with_displayable_images, with_stored_images, published_dogs


PROFILE_RELATION_PREVIEW_LIMIT = 18
SEARCH_HIT_THROTTLE_SECONDS = 30


def _dog_cards(queryset, *, include_parents=False, include_sources=True, include_registrations=True, include_images=True):
    related = ["kennel"]
    if include_parents:
        related.extend(["sire", "dam"])

    prefetches = []
    if include_images:
        prefetches.append(
            Prefetch(
                "images",
                queryset=DogImage.objects.order_by("-is_primary", "sort_order", "created_at"),
                to_attr="display_images",
            )
        )
    if include_registrations:
        prefetches.append(
            Prefetch(
                "registrations",
                queryset=DogRegistration.objects.select_related("authority"),
                to_attr="display_registrations",
            )
        )
    queryset = queryset.select_related(*related).prefetch_related(*prefetches)
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
    return with_displayable_images(published_dogs())


def _attach_source_images_for_missing(dogs):
    """Load source-image metadata only for cards that do not already have stored media."""
    missing = [
        dog for dog in dogs
        if not getattr(dog, "display_images", [])
        and not getattr(dog, "card_image_url", "")
    ]
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

    # Typed lookup is a registry search, not a photo gallery. Every published
    # dog must be discoverable even when a photograph has not been uploaded.
    # Keep the image requirement only for the unfiltered browse picker.
    dogs = published_dogs()
    if not query and browse:
        dogs = with_displayable_images(dogs)

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
    suggestions = dogs.annotate(_registration=Subquery(registration_number))
    if query:
        # Exact typed names outrank popular substring matches. Otherwise a
        # recently published / low-traffic dog can disappear from autocomplete.
        suggestions = suggestions.annotate(
            _match_priority=Case(
                When(name__iexact=query, then=Value(0)),
                When(name__istartswith=query, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("_match_priority", "-search_count", "name")
    else:
        suggestions = suggestions.order_by("-search_count", "-updated_at", "name")
    rows = list(
        suggestions.values(
            "id", "name", "slug", "sex", "kennel__name", "_registration"
        )[:suggestion_limit]
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
    response["Cache-Control"] = "no-store"
    return response


def dog_search(request):
    query = request.GET.get("q", "").strip()
    sex = request.GET.get("sex", "").strip()
    country = request.GET.get("country", "").strip()
    kennel_slug = request.GET.get("kennel", "").strip()
    exact = request.GET.get("exact") == "1"

    if query:
        # An explicit name/alias/registration search must find published dogs
        # irrespective of the completeness of their image gallery.
        base_dogs = published_dogs().filter(
            public_dog_match_filter(query, exact=exact)
        )
    else:
        base_dogs = _public_dogs_with_images()
    # Rank and paginate lightweight dog IDs first. Card image/registration
    # subqueries must NOT be part of the ROW_NUMBER kennel ranking: doing so
    # computed correlated card details for all matched dogs, costing seconds.
    dogs = base_dogs
    if sex in {Dog.Sex.MALE, Dog.Sex.FEMALE, Dog.Sex.UNKNOWN}:
        dogs = dogs.filter(sex=sex)
    if country:
        dogs = dogs.filter(country__iexact=country)
    if kennel_slug:
        dogs = dogs.filter(kennel__slug=kennel_slug)

    if not query and not kennel_slug:
        dogs = one_dog_per_kennel(dogs)

    dogs = dogs.order_by("name") if query else dogs.order_by("-search_count", "-updated_at", "name")
    paginator = Paginator(dogs.values_list("pk", flat=True), 18)
    if not query and not sex and not country and not kennel_slug:
        cached_count = cache.get("cca:dog-search:default-count:v1")
        # Corrupt/legacy cache values must never turn public browsing into
        # a 500. Only a nonnegative integer is a valid cached paginator count.
        if type(cached_count) is not int or cached_count < 0:
            cached_count = paginator.count
            cache.set("cca:dog-search:default-count:v1", cached_count, 900)
        paginator.__dict__["count"] = cached_count
    page_obj = paginator.get_page(request.GET.get("page"))
    page_ids = list(page_obj.object_list)
    # Only the <=18 dogs on this page need their displayed media,
    # registration and kennel. The order from the ranked ID query wins.
    card_rows = with_card_image(with_card_registration(
        _dog_cards(
            published_dogs(Dog.objects.filter(pk__in=page_ids)),
            include_sources=False, include_registrations=False,
            include_images=False,
        )
    ))
    cards_by_id = {dog.pk: dog for dog in card_rows}
    page_obj.object_list = [
        cards_by_id[dog_id] for dog_id in page_ids if dog_id in cards_by_id
    ]
    for dog in page_obj.object_list:
        dog.card_image_url = default_storage.url(dog.card_image_name) if dog.card_image_name else ""
    _attach_source_images_for_missing(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)

    countries = cache.get("cca:dog-search:countries:v3")
    if countries is None:
        countries = list(
            with_displayable_images(published_dogs())
            .exclude(country="")
            .values_list("country", flat=True)
            .distinct()
            .order_by("country")
        )
        cache.set("cca:dog-search:countries:v3", countries, 900)

    kennels = cache.get("cca:dog-search:kennels:v3")
    if kennels is None:
        displayable_kennel_ids = (
            with_displayable_images(
                published_dogs(Dog.objects.filter(kennel__isnull=False))
            )
            .order_by()
            .values("kennel_id")
            .distinct()
        )
        kennels = list(
            Kennel.objects.filter(pk__in=Subquery(displayable_kennel_ids))
            .order_by("name")
            .values("name", "slug")
        )
        cache.set("cca:dog-search:kennels:v3", kennels, 900)

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


def _public_profile_dog(slug):
    """Load published profile sections only when they have actual rows.

    Cheap correlated EXISTS checks are part of the indexed dog lookup and
    avoid separate remote database round trips for empty image, title,
    registration and published-document collections.
    """
    dogs = (
        published_dogs()
        .select_related("kennel", "inferred_kennel", "sire", "dam", "sire__kennel", "dam__kennel")
        .annotate(
            _has_profile_images=Exists(
                DogImage.objects.filter(dog_id=OuterRef("pk"))
            ),
            _has_profile_registrations=Exists(
                DogRegistration.objects.filter(dog_id=OuterRef("pk"))
            ),
            _has_profile_titles=Exists(
                DogTitle.objects.filter(dog_id=OuterRef("pk"))
            ),
            _has_public_documents=Exists(
                DogDocument.objects.filter(dog_id=OuterRef("pk"), is_public=True)
            ),
            _has_profile_sources=Exists(
                DogSource.objects.filter(dog_id=OuterRef("pk"))
            ),
            _has_public_offspring=Exists(
                published_dogs().filter(
                    Q(sire_id=OuterRef("pk")) | Q(dam_id=OuterRef("pk"))
                )
            ),
            _has_subject_health=Exists(
                HealthRecord.objects.filter(dog_id=OuterRef("pk"), is_public=True)
            ),
            _has_breed_dna=Exists(
                BreedDNAReport.objects.filter(health_record__dog_id=OuterRef("pk"), consent_public_summary=True)
            ),
        )
    )
    dog = dogs.filter(slug=slug).first()
    if dog is None:
        return None

    dog.display_images = (
        list(DogImage.objects.filter(dog=dog).order_by(
            "-is_primary", "sort_order", "created_at"
        )) if dog._has_profile_images else []
    )
    dog.display_registrations = (
        list(DogRegistration.objects.filter(dog=dog).select_related("authority"))
        if dog._has_profile_registrations else []
    )
    dog.display_titles = (
        list(DogTitle.objects.filter(dog=dog).order_by("name"))
        if dog._has_profile_titles else []
    )
    dog.display_documents = (
        list(DogDocument.objects.filter(dog=dog, is_public=True).exclude(source_submission__kind="health").order_by("-created_at"))
        if dog._has_public_documents else []
    )
    # The approved source text holds a reference to the reviewed document.
    # Keep public and private certificate access separate, without schema changes.
    title_doc_ids = {}
    for item in dog.display_titles:
        matched = re.search(r"\[CCA certificate #(\d+)\]", item.source_text or "")
        if matched:
            title_doc_ids[item.pk] = int(matched.group(1))
    if title_doc_ids:
        evidence = DogDocument.objects.filter(
            dog=dog, pk__in=set(title_doc_ids.values()),
        ).in_bulk()
        for item in dog.display_titles:
            item.display_certificate = evidence.get(title_doc_ids.get(item.pk))
    dog.display_source_media = (
        list(DogSource.objects.filter(dog=dog).order_by("-verified_at", "-created_at"))
        if not dog.display_images and dog._has_profile_sources else []
    )
    _attach_source_image_urls([dog])
    return dog


def dog_detail(request, slug):
    dog = _public_profile_dog(slug)
    if dog is None:
        old = DogRedirect.objects.select_related("dog").filter(old_slug=slug).first()
        if old and old.dog.is_effectively_public:
            return redirect("registry:dog-detail", slug=old.dog.slug, permanent=True)
        return get_object_or_404(published_dogs(), slug=slug)


    # All available published direct ancestors are included by default.
    # Members and active assigned staff can compare depths, across all devices.
    # Guests retain the full published-ancestry default without a selector.
    # Missing/unpublished parentage must not be misreported as a true zero.
    can_select_coi = can_access_public_pedigree_analysis(request.user)
    coi_generations = (
        requested_coi_generations(request.GET.get("coi_generations"))
        if can_select_coi else None
    )
    coi_label = f"{coi_generations} generations" if coi_generations is not None else "all available generations"
    coi_options = [
        {"value": "all", "label": "All available", "selected": coi_generations is None},
        *[
            {"value": str(depth), "label": f"{depth} generations", "selected": coi_generations == depth}
            for depth in COI_GENERATION_CHOICES
        ],
    ]
    public_coi = public_profile_coi(dog, generations=coi_generations)
    public_parentage_complete = public_coi["public_parentage_complete"]
    coi_display_state = public_coi["coi_display_state"]
    coi_percent = public_coi["coi_percent"]
    coi_error = public_coi["coi_error"]
    coi_below_display_precision = public_coi["coi_below_display_precision"]

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
    if dog.kennel and dog.kennel.is_public:
        structured_data["isPartOf"] = {
            "@type": "Organization",
            "name": dog.kennel.name,
            "url": request.build_absolute_uri(reverse("registry:kennel-detail", args=[dog.kennel.slug])),
        }

    relation_limit = PROFILE_RELATION_PREVIEW_LIMIT
    # A single bounded SQL request retrieves both relationship previews.
    # The extra row in each category preserves accurate truncation indicators.
    if dog.sire_id or dog.dam_id or dog._has_public_offspring:
        sibling_rows, offspring_rows = profile_direct_relations(
            dog, limit=relation_limit + 1
        )
    else:
        # Unknown parents rule out siblings; the indexed EXISTS above also
        # confirms there are no public offspring, so no relationship query.
        sibling_rows, offspring_rows = [], []
    siblings_truncated = len(sibling_rows) > relation_limit
    siblings = sibling_rows[:relation_limit]
    offspring_truncated = len(offspring_rows) > relation_limit
    offspring = offspring_rows[:relation_limit]

    mate_rows = mate_relationships(
        dog,
        children=offspring_rows,
        exact_counts=offspring_truncated,
    )
    mates_truncated = len(mate_rows) > relation_limit
    mates = mate_rows[:relation_limit]

    # Fetch the subject's tests and its relatives' tests together, preserving
    # each section while avoiding a separate network round trip to PostgreSQL.
    if dog._has_subject_health or dog.sire_id or dog.dam_id or siblings or offspring:
        relative_health, dog.display_health_records = direct_relative_health(
            dog,
            sibling_rows=siblings,
            children=offspring,
            include_subject_records=True,
        )
    else:
        # Neither the subject nor any public direct relative can have rows
        # to display. Preserve the empty Health & DNA section in the template.
        relative_health, dog.display_health_records = [], []

    # The public verification card must show reviewed data, not a generic placeholder.
    genetic_screenings = marker_status_rows(dog.display_health_records)
    # Only actual recorded marker statuses are displayed; never invent missing results.
    # Additional conditions are sourced from a moderator-reviewed approval event,
    # not an untrusted string in the member's original notes.
    possible_extra_ids = [
        record.pk for record in dog.display_health_records
        if (record.notes or "").startswith("Moderator condition transcribed from ")
    ]
    confirmed_extra_ids = set(
        VerificationEvent.objects.filter(
            health_record_id__in=possible_extra_ids,
            note__startswith="Additional condition manually checked against approved private laboratory report ",
        ).values_list("health_record_id", flat=True)
    ) if possible_extra_ids else set()
    verified_clinical_extras = {
        record.pk for record in dog.display_health_records
        if record.pk in confirmed_extra_ids
        and (record.notes or "").endswith("; evidence_category=health")
    }
    seen_additional = set()
    for record in sorted(dog.display_health_records, key=lambda item: (item.created_at, item.pk), reverse=True):
        label = (record.test_type or "").strip()
        if (record.pk not in confirmed_extra_ids or record.pk in verified_clinical_extras
                or not label or label.upper() in MARKER_CODES):
            continue
        if label.casefold() in seen_additional:
            continue
        seen_additional.add(label.casefold())
        status = (record.result or "").strip()
        classified = SCREENING_RESULTS.get(status.lower())
        genetic_screenings.append({
            "code": label, "name": "Additional laboratory screening",
            "status": classified[0] if classified else (status or "Result unclear"),
            "tone": classified[1] if classified else "other",
        })
    # Older data may have a single free-text health row combining an alleged
    # breed percentage with words such as "DSRA CLEAR". Never treat that prose
    # as an independently reviewed breed-composition report or genetic test.
    # Keep such text in the private moderation database for correction.
    other_health_records = []
    other_health_rows = []
    orthopaedic_screenings = []
    for record in dog.display_health_records:
        label = (record.test_type or "").strip().lower()
        if (label.upper() in MARKER_CODES and record.verification_state == VerificationState.HEALTH_VERIFIED) or (
            record.pk in confirmed_extra_ids and record.pk not in verified_clinical_extras
        ):
            continue  # Reviewed genetic markers are already displayed in the DNA card.
        legacy_rows = legacy_mixed_health_rows(
            record.test_type, record.result,
            record_verified=record.verification_state == VerificationState.HEALTH_VERIFIED,
        )
        if legacy_rows is not None:
            # Original evidence stays unchanged: reviewed health markers do not
            # imply that the breed percentage has independent DNA verification.
            other_health_rows.extend(legacy_rows)
            other_health_records.append(record)
            continue
        if unstructured_breed_claim(record.test_type):
            continue  # Only BreedDNAReport + owner consent enables public breed percent.
        interpreted = describe_orthopaedic_result(record.test_type, record.result)
        if interpreted:
            verified = record.verification_state == VerificationState.HEALTH_VERIFIED
            pedigree_source = "supplied pedigree" in (record.result or "").lower()
            for assessment in interpreted:
                details = dict(assessment)
                if not verified:
                    details["tone"] = "unverified"
                    # The public row uses a short result and a separate Not verified label.
                    details["explanation"] = (
                        "The supplied pedigree lists " + assessment["grade"] + ". "
                        if pedigree_source else
                        "The available record lists " + assessment["grade"] + ". "
                    ) + "This grade has not been independently verified against a veterinary screening report."
                    details["source_label"] = (
                        "Source: supplied pedigree" if pedigree_source else "Source: unverified record"
                    )
                else:
                    details["source_label"] = "Veterinary evidence reviewed"
                orthopaedic_screenings.append({
                    **details,
                    "tested_on": record.tested_on,
                    "verification_label": record.public_verification_label,
                })
            continue  # Display recognized grades as two separately explained findings.
        other_health_records.append(record)
        other_health_rows.append({
            "test": record.test_type,
            "result": readable_health_result(record.result) or "Result not provided",
            "verified": record.verification_state == VerificationState.HEALTH_VERIFIED,
        })

    # Surface only moderator-reviewed lab estimates, never pending submissions.
    breed_dna = (
        BreedDNAReport.objects.filter(
            health_record__dog=dog,
            health_record__verification_state=VerificationState.HEALTH_VERIFIED,
            health_record__is_public=True,
            consent_public_summary=True,
        ).select_related("health_record", "evidence_document")
        .order_by("-health_record__tested_on", "-health_record__created_at").first()
        if dog._has_breed_dna else None
    )
    can_submit_breed_dna = (
        can_contribute_to_dog(request.user, dog)
        and dog.kennel_id is not None
        and dog.kennel.memberships.filter(
            user=request.user, role="owner"
        ).exists()
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
            "breed_dna": breed_dna,
            "breed_dna_percentage": percentage_text(breed_dna.cane_corso_percentage) if breed_dna else "",
            "genetic_screenings": genetic_screenings,
            "other_health_records": other_health_records,
            "other_health_rows": other_health_rows,
            "orthopaedic_screenings": orthopaedic_screenings,
            "show_dna_card": bool(breed_dna or genetic_screenings),
            "has_public_health_records": bool(other_health_records or orthopaedic_screenings or breed_dna or genetic_screenings),
            "can_submit_breed_dna": can_submit_breed_dna,
            "coi_percent": coi_percent,
            "can_select_coi": can_select_coi,
            "coi_label": coi_label,
            "coi_options": coi_options,
            "coi_error": coi_error,
            "coi_display_state": coi_display_state,
            "coi_below_display_precision": coi_below_display_precision,
            "public_parentage_complete": public_parentage_complete,
            "verification_label": public_verification_label(dog.verification_state),
            "has_source_attribution": dog._has_profile_sources,
            "relation_limit": relation_limit,
            "can_contribute": can_contribute_to_dog(request.user, dog),
            "structured_data": json_ld(structured_data),
        },
    )


def _top_public_parents(parent_field, sex):
    relation = parent_field.removesuffix("_id")
    rows = list(
        published_dogs(Dog.objects.filter(
            **{
                f"{relation}__is_public": True,
                f"{relation}__hidden_by_moderation": False,
                f"{relation}__sex": sex,
            },
        )).filter(
            Q(**{f"{relation}__kennel__isnull": True}) | Q(**{f"{relation}__kennel__hide_dogs": False})
        )
        .values(parent_field)
        .annotate(public_offspring_count=Count("id"))
        .order_by("-public_offspring_count")[:20]
    )
    parent_ids = [row[parent_field] for row in rows]
    parents = published_dogs(Dog.objects.filter(
        pk__in=parent_ids, sex=sex,
    )).in_bulk()
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
        Kennel.objects.filter(is_public=True, hide_dogs=False).annotate(
            public_dog_count=Count(
                "dogs", filter=Q(dogs__is_public=True, dogs__hidden_by_moderation=False), distinct=True
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
        published_dogs(Dog.objects.filter(kennel_id=OuterRef("pk")))
        .values("kennel_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    public_litter_count = (
        Litter.objects.filter(kennel_id=OuterRef("pk"), is_public=True, kennel__hide_dogs=False)
        .values("kennel_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    inferred_dog_count = (
        published_dogs(
            Dog.objects.filter(
                inferred_kennel_id=OuterRef("pk"), kennel__isnull=True
            )
        )
        .values("inferred_kennel_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    kennels = Kennel.objects.filter(is_public=True).annotate(
        possible_breeding_dog_count=Coalesce(
            Subquery(inferred_dog_count, output_field=IntegerField()), Value(0)
        ),
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
    kennel = get_object_or_404(Kennel, slug=slug, is_public=True)
    public_dogs = published_dogs(Dog.objects.filter(kennel=kennel))
    public_dog_total = public_dogs.count()
    stored_image_exists = DogImage.objects.filter(dog_id=OuterRef("pk"))
    source_image_exists = DogSource.objects.filter(
        dog_id=OuterRef("pk"),
    ).filter(
        Q(raw_payload__image_url__startswith="https://www.canecorsopedigree.com/static/images/animal/")
        | Q(raw_payload__image_url__startswith="https://canecorsopedigree.com/static/images/animal/")
    )
    dog_queryset = _dog_cards(
        public_dogs.annotate(
            _has_stored_image=Exists(stored_image_exists),
            _has_source_image=Exists(source_image_exists),
        ).filter(
            Q(_has_stored_image=True) | Q(_has_source_image=True)
        ),
        include_sources=False,
    ).order_by("name")
    # Existing dogs can have a research association without declaring an
    # unverified kennel to be their actual breeding origin.
    possible_bred_dogs = published_dogs(
        Dog.objects.filter(inferred_kennel=kennel, kennel__isnull=True)
    )
    possible_bred_count = possible_bred_dogs.count()
    possible_dogs_page = Paginator(
        _dog_cards(possible_bred_dogs, include_sources=False).order_by("name"), 24
    ).get_page(request.GET.get("research_page"))
    _attach_source_images_for_missing(possible_dogs_page.object_list)
    litter_queryset = (
        Litter.objects.filter(kennel=kennel, is_public=True, kennel__hide_dogs=False)
        .select_related("sire", "dam", "sire__kennel", "dam__kennel")
        .order_by("-date_of_birth", "code")
    )
    dog_page = Paginator(dog_queryset, 24).get_page(request.GET.get("dogs_page"))
    _attach_source_images_for_missing(dog_page.object_list)
    litter_page = Paginator(litter_queryset, 20).get_page(request.GET.get("litters_page"))
    # Anonymous kennel browsing must not fetch private claim/ownership facts.
    # These queries are expensive against the remote production database.
    is_member = False
    kennel_linked = False
    pending_claim_owner_id = None
    if request.user.is_authenticated:
        is_member = request.user.kennel_memberships.filter(kennel=kennel).exists()
        kennel_linked = kennel.memberships.exists()
        pending_claim_owner_id = (
            Submission.objects.filter(
                kind=Submission.Kind.KENNEL_CLAIM,
                status=Submission.Status.PENDING,
                kennel=kennel,
            )
            .values_list("submitted_by_id", flat=True)
            .first()
        )
    claim_in_review = pending_claim_owner_id is not None
    claim_pending = claim_in_review and pending_claim_owner_id == request.user.pk
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
            "possible_dogs": possible_dogs_page.object_list,
            "possible_dog_page": possible_dogs_page,
            "possible_bred_count": possible_bred_count,
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
        Litter.objects.select_related("kennel", "sire", "dam", "sire__kennel", "dam__kennel").filter(
            Q(kennel__isnull=True) | Q(kennel__hide_dogs=False)
        ),
        pk=pk,
        is_public=True,
    )
    offspring = list(
        _dog_cards(
            published_dogs(Dog.objects.filter(litter=litter))
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
