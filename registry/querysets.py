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
    """Build one lazy, index-friendly public search predicate.

    Keeping aliases, registrations and kennels as SQL subqueries avoids the
    extra application/database round trips that the previous eager ID lists
    introduced. It also lets PostgreSQL use the trigram indexes on the main
    dog-name and bloodline branches before ranking the small match set.
    """
    lookup = "iexact" if exact else "icontains"
    match = Q(**{f"name__{lookup}": value})

    if not exact:
        match |= Q(**{f"bloodline__{lookup}": value})

    match |= Q(
        pk__in=DogAlias.objects.filter(**{f"name__{lookup}": value})
        .order_by()
        .values("dog_id")
    )
    match |= Q(
        pk__in=DogRegistration.objects.filter(**{f"number__{lookup}": value})
        .order_by()
        .values("dog_id")
    )

    if not exact:
        match |= Q(
            kennel_id__in=Kennel.objects.filter(**{f"name__{lookup}": value})
            .order_by()
            .values("pk")
        )

    return match
