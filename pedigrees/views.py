import csv

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from registry.models import Dog

from .services import (
    common_ancestors,
    descendant_generations,
    pedigree_analysis,
    pedigree_export_rows,
    projected_inbreeding,
)


ALLOWED_GENERATIONS = {4, 6, 8, 10}


def _public_dogs():
    return Dog.objects.filter(is_public=True).select_related("kennel", "sire", "dam")


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
        dogs = dogs.filter(
            Q(name__icontains=query)
            | Q(bloodline__icontains=query)
            | Q(aliases__name__icontains=query)
            | Q(kennel__name__icontains=query)
            | Q(registrations__number__icontains=query)
        ).distinct()
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
        dog, generations=generations, public_only=True
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
        },
    )


def virtual_mating(request):
    sires = _public_dogs().filter(sex=Dog.Sex.MALE).order_by("name")
    dams = _public_dogs().filter(sex=Dog.Sex.FEMALE).order_by("name")

    sire = None
    dam = None
    projected_percent = None
    common = []
    error = ""

    sire_id = request.GET.get("sire", "").strip()
    dam_id = request.GET.get("dam", "").strip()
    if sire_id:
        sire = sires.filter(pk=sire_id).first()
    if dam_id:
        dam = dams.filter(pk=dam_id).first()

    if sire and dam:
        try:
            projected_percent = projected_inbreeding(
                sire, dam, public_only=True
            ) * 100
            common = common_ancestors(
                sire, dam, generations=10, public_only=True
            )
        except ValueError as exc:
            error = str(exc)

    return render(
        request,
        "pedigrees/virtual_mating.html",
        {
            "sires": sires,
            "dams": dams,
            "sire": sire,
            "dam": dam,
            "projected_percent": projected_percent,
            "common": common,
            "error": error,
        },
    )
