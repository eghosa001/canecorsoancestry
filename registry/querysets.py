from django.db.models import Exists, F, OuterRef, Q, Window
from django.db.models.functions import Coalesce, RowNumber

from .models import Dog, DogAlias, DogImage, DogRegistration


def with_stored_images(queryset):
    return queryset.annotate(
        _has_stored_image=Exists(
            DogImage.objects.filter(dog_id=OuterRef("pk"))
        )
    ).filter(_has_stored_image=True)


def one_dog_per_kennel(queryset):
    group = Coalesce("kennel_id", "id")
    return queryset.annotate(
        _kennel_display_rank=Window(
            expression=RowNumber(),
            partition_by=[group],
            order_by=[
                F("search_count").desc(),
                F("updated_at").desc(),
                F("name").asc(),
            ],
        )
    ).filter(_kennel_display_rank=1)



def matching_public_dog_ids(value, *, exact=False):
    lookup = "iexact" if exact else "icontains"

    direct_filter = Q(**{f"name__{lookup}": value})
    if not exact:
        direct_filter |= Q(**{f"bloodline__{lookup}": value})

    direct = (
        Dog.objects.filter(is_public=True)
        .filter(direct_filter)
        .order_by()
        .values_list("pk", flat=True)
    )
    aliases = (
        DogAlias.objects.filter(
            dog__is_public=True,
            **{f"name__{lookup}": value},
        )
        .order_by()
        .values_list("dog_id", flat=True)
    )
    registrations = (
        DogRegistration.objects.filter(
            dog__is_public=True,
            **{f"number__{lookup}": value},
        )
        .order_by()
        .values_list("dog_id", flat=True)
    )

    if exact:
        return direct.union(aliases, registrations)

    kennel_matches = (
        Dog.objects.filter(
            is_public=True,
            **{f"kennel__name__{lookup}": value},
        )
        .order_by()
        .values_list("pk", flat=True)
    )
    return direct.union(aliases, registrations, kennel_matches)
