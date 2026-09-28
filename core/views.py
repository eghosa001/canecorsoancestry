from django.shortcuts import render

from registry.models import Dog, Kennel, Litter


def home(request):
    context = {
        "dog_count": Dog.objects.filter(is_public=True).count(),
        "kennel_count": Kennel.objects.count(),
        "litter_count": Litter.objects.count(),
    }
    return render(request, "core/home.html", context)
