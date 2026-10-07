from django.db.models import Exists, F, OuterRef, Q, Subquery, Window
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




def public_dog_match_filter(value, *, exact=False):
    """Match public dogs through independently indexable candidate branches.

    PostgreSQL can choose the trigram/relationship index for each UNION branch,
    then rank only the small candidate set in the outer query. A single large
    OR across dog, kennel, alias and registration fields encouraged production
    to scan the popularity index and filter most of the dog table.
    """
    lookup = "iexact" if exact else "icontains"

    candidates = [
        Dog.objects.filter(
            is_public=True,
            **{f"name__{lookup}": value},
        ).order_by().values("pk"),
        DogAlias.objects.filter(
            dog__is_public=True,
            **{f"name__{lookup}": value},
        ).order_by().values("dog_id"),
        DogRegistration.objects.filter(
            dog__is_public=True,
            **{f"number__{lookup}": value},
        ).order_by().values("dog_id"),
    ]

    if not exact:
        candidates.extend(
            [
                Dog.objects.filter(
                    is_public=True,
                    **{f"bloodline__{lookup}": value},
                ).order_by().values("pk"),
                Dog.objects.filter(
                    is_public=True,
                    **{f"kennel__name__{lookup}": value},
                ).order_by().values("pk"),
            ]
        )

    matched_ids = candidates[0].union(*candidates[1:])
    return Q(pk__in=Subquery(matched_ids))
