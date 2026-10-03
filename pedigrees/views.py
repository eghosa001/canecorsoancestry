import csv
from uuid import UUID

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from registry.models import Dog
from registry.querysets import public_dog_match_filter

from .services import (
    descendant_generations,
    pedigree_analysis,
    pedigree_export_rows,
    virtual_mating_analysis,
)


ALLOWED_GENERATIONS = {4, 6, 8, 10}


def _public_dogs():
    return Dog.objects.filter(is_public=True).select_related("kennel")


def _requested_generations(request):
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    return requested if requested in ALLOWED_GENERATIONS else 4


def _csv_response(dog, generations, public_only=True):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{dog.slug}-pedigree-{generations}g.csv"'
    )
    writer = csv.DictWriter(
        response,
        fieldnames=(
            "generation",
            "path",
            "dog_id",
            "name",
            "sex",
            "date_of_birth",
            "colour",
            "country",
            "kennel",
            "repeated",
            "path_contribution_percent",
        ),
    )
    writer.writeheader()
    writer.writerows(
        pedigree_export_rows(dog, generations, public_only=public_only)
    )
    return response


def pedigree_index(request):
    query = request.GET.get("q", "").strip()
    dogs = _public_dogs()
    if query:
        dogs = dogs.filter(public_dog_match_filter(query))
    else:
        dogs = dogs.order_by("name")[:24]
    return render(request, "pedigrees/index.html", {"dogs": dogs, "query": query})


def pedigree_detail(request, slug):
    dog = get_object_or_404(_public_dogs(), slug=slug)
    generations = _requested_generations(request)
    analysis = pedigree_analysis(dog, generations, public_only=True)

    context = {
        "dog": dog,
        "generations": generations,
        "generation_options": sorted(ALLOWED_GENERATIONS),
        "analysis": analysis,
        "layers": analysis["layers"],
        "repeated": analysis["repeated"],
        "coi_percent": analysis["coi_percent"],
        "cycle_error": analysis["cycle_error"],
        "member_mode": False,
    }
    return render(request, "pedigrees/pedigree_detail.html", context)


def pedigree_export(request, slug):
    dog = get_object_or_404(_public_dogs(), slug=slug)
    return _csv_response(dog, _requested_generations(request), public_only=True)


def reverse_pedigree(request, slug):
    dog = get_object_or_404(_public_dogs(), slug=slug)
    generations = _requested_generations(request)
    layers = descendant_generations(
        dog,
        generations=generations,
        public_only=True,
        per_generation_limit=1000,
    )
    return render(
        request,
        "pedigrees/reverse_pedigree.html",
        {
            "dog": dog,
            "generations": generations,
            "generation_options": sorted(ALLOWED_GENERATIONS),
            "layers": layers,
            "descendant_total": sum(len(layer["dogs"]) for layer in layers),
            "descendants_truncated": any(
                layer.get("truncated") for layer in layers
            ),
        },
    )


def _resolve_mating_dog(raw_value, expected_sex, selected_id=""):
    query = (raw_value or "").strip()
    candidates = _public_dogs().filter(
        Q(sex=expected_sex) | Q(sex=Dog.Sex.UNKNOWN)
    )

    selected = (selected_id or "").strip()
    if selected:
        try:
            selected_uuid = UUID(selected)
        except (TypeError, ValueError):
            selected_uuid = None
        if selected_uuid:
            dog = candidates.filter(pk=selected_uuid).first()
            if dog:
                return dog, ""

    if not query:
        return None, ""

    try:
        dog_id = UUID(query)
    except (TypeError, ValueError):
        dog_id = None
    if dog_id:
        dog = candidates.filter(pk=dog_id).first()
        if dog:
            return dog, ""

    exact_names = list(
        candidates.filter(name__iexact=query).order_by("name")[:2]
    )
    if len(exact_names) == 1:
        return exact_names[0], ""
    if len(exact_names) > 1:
        return None, "More than one dog has that exact name. Select a suggestion or use a registration number."

    exact_other = list(
        candidates.filter(
            Q(aliases__name__iexact=query)
            | Q(registrations__number__iexact=query)
        )
        .distinct()
        .order_by("name")[:2]
    )
    if len(exact_other) == 1:
        return exact_other[0], ""
    if len(exact_other) > 1:
        return None, "More than one dog matches that value. Select a suggestion or use a registration number."

    partial = list(
        candidates.filter(
            Q(name__icontains=query)
            | Q(aliases__name__icontains=query)
            | Q(registrations__number__icontains=query)
        )
        .distinct()
        .order_by("name")[:3]
    )
    if len(partial) == 1:
        return partial[0], ""
    if len(partial) > 1:
        names = ", ".join(dog.name for dog in partial)
        return None, f"Multiple matches found: {names}. Enter a more exact name or registration."
    return None, "No matching public dog was found."


def virtual_mating(request):
    sire_query = (request.GET.get("sire_q") or "").strip()
    dam_query = (request.GET.get("dam_q") or "").strip()
    sire_id = (request.GET.get("sire") or "").strip()
    dam_id = (request.GET.get("dam") or "").strip()

    sire = dam = None
    sire_error = dam_error = ""

    try:
        sire_uuid = UUID(sire_id) if sire_id else None
    except (TypeError, ValueError):
        sire_uuid = None
    try:
        dam_uuid = UUID(dam_id) if dam_id else None
    except (TypeError, ValueError):
        dam_uuid = None

    if sire_uuid and dam_uuid:
        selected = _public_dogs().filter(
            pk__in=(sire_uuid, dam_uuid)
        ).in_bulk()
        candidate_sire = selected.get(sire_uuid)
        candidate_dam = selected.get(dam_uuid)
        if candidate_sire and candidate_sire.sex in {Dog.Sex.MALE, Dog.Sex.UNKNOWN}:
            sire = candidate_sire
        if candidate_dam and candidate_dam.sex in {Dog.Sex.FEMALE, Dog.Sex.UNKNOWN}:
            dam = candidate_dam

    if sire is None:
        sire, sire_error = _resolve_mating_dog(
            sire_query, Dog.Sex.MALE, selected_id=sire_id
        )
    if dam is None:
        dam, dam_error = _resolve_mating_dog(
            dam_query, Dog.Sex.FEMALE, selected_id=dam_id
        )

    error = sire_error or dam_error
    projected_percent = None
    common = []

    if sire and dam and not error:
        try:
            analysis = virtual_mating_analysis(
                sire,
                dam,
                generations=10,
                public_only=True,
            )
            projected_percent = analysis["projected_inbreeding"] * 100
            common = analysis["common"]
        except ValueError as exc:
            error = str(exc)

    return render(
        request,
        "pedigrees/virtual_mating.html",
        {
            "sire": sire,
            "dam": dam,
            "sire_query": sire.name if sire else sire_query,
            "dam_query": dam.name if dam else dam_query,
            "projected_percent": projected_percent,
            "common": common,
            "error": error,
        },
    )
