from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from registry.models import Dog

from .services import (
    PedigreeCycleError,
    common_ancestors,
    inbreeding_coefficient,
    pedigree_generations,
    projected_inbreeding,
    repeated_ancestors,
)


ALLOWED_GENERATIONS = {4, 6, 8, 10}


def _public_dogs():
    return Dog.objects.filter(is_public=True).select_related("kennel", "sire", "dam")


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
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in ALLOWED_GENERATIONS else 4

    try:
        coi_percent = inbreeding_coefficient(dog, public_only=True) * 100
        cycle_error = ""
    except PedigreeCycleError:
        coi_percent = None
        cycle_error = "This pedigree contains a parent cycle and cannot be analysed safely."

    context = {
        "dog": dog,
        "generations": generations,
        "generation_options": sorted(ALLOWED_GENERATIONS),
        "layers": pedigree_generations(dog, generations, public_only=True),
        "repeated": repeated_ancestors(dog, generations, public_only=True),
        "coi_percent": coi_percent,
        "cycle_error": cycle_error,
    }
    return render(request, "pedigrees/pedigree_detail.html", context)


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
        except (PedigreeCycleError, ValueError) as exc:
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
