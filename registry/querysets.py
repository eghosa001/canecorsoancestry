from django.db.models import Exists, F, OuterRef, Q, Window
from django.db.models.functions import Coalesce, RowNumber

from .models import DogAlias, DogImage, DogRegistration, Kennel


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




def public_dog_match_filter(value, *, exact=False):
    lookup = "iexact" if exact else "icontains"
    match = Q(**{f"name__{lookup}": value})

    if not exact:
        match |= Q(**{f"bloodline__{lookup}": value})

    related_ids = set(
        DogAlias.objects.filter(**{f"name__{lookup}": value})
        .order_by()
        .values_list("dog_id", flat=True)
    )
    related_ids.update(
        DogRegistration.objects.filter(**{f"number__{lookup}": value})
        .order_by()
        .values_list("dog_id", flat=True)
    )
    if related_ids:
        match |= Q(pk__in=related_ids)

    if not exact:
        kennel_ids = list(
            Kennel.objects.filter(**{f"name__{lookup}": value})
            .order_by()
            .values_list("pk", flat=True)
        )
        if kennel_ids:
            match |= Q(kennel_id__in=kennel_ids)

    return match
