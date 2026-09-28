from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from pedigrees.services import build_pedigree, repeated_ancestors

from .models import Dog


def dog_search(request):
    query = request.GET.get("q", "").strip()
    dogs = Dog.objects.filter(is_public=True).select_related("kennel", "sire", "dam")
    if query:
        dogs = dogs.filter(
            Q(name__icontains=query)
            | Q(aliases__name__icontains=query)
            | Q(registrations__number__icontains=query)
        ).distinct()
    else:
        dogs = dogs.none()
    return render(request, "registry/dog_search.html", {"dogs": dogs, "query": query})


def dog_detail(request, slug):
    dog = get_object_or_404(
        Dog.objects.select_related("kennel", "sire", "dam"),
        slug=slug,
        is_public=True,
    )
    context = {
        "dog": dog,
        "pedigree": build_pedigree(dog, generations=4),
        "repeated": repeated_ancestors(dog, generations=4),
    }
    return render(request, "registry/dog_detail.html", context)
