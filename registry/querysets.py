from django.db.models import F, OuterRef, Q, Subquery, Window
from django.db.models.functions import Coalesce, RowNumber

from .models import Dog, DogAlias, DogImage, DogRegistration, DogSource


def with_stored_images(queryset):
    """Restrict to dogs with managed images using one deduplicated ID set.

    DISTINCT encourages PostgreSQL to hash the imaged-dog IDs once instead of
    probing DogImage for every candidate dog in popularity-ranked listings.
    """
    image_dog_ids = DogImage.objects.order_by().values("dog_id").distinct()
    return queryset.filter(pk__in=Subquery(image_dog_ids))


def with_displayable_images(queryset):
    """Restrict public discovery to dogs that can render a real photograph.

    Managed uploads are preferred. Trusted imported CaneCorsoPedigree image
    URLs are also valid display media so legacy records with a genuine photo
    are not hidden merely because the photo has not been copied into R2 yet.
    """
    managed_ids = DogImage.objects.order_by().values("dog_id").distinct()
    source_ids = (
        DogSource.objects.filter(
            Q(
                raw_payload__image_url__startswith=(
                    "https://canecorsopedigree.com/static/images/animal/"
                )
            )
            | Q(
                raw_payload__image_url__startswith=(
                    "https://www.canecorsopedigree.com/static/images/animal/"
                )
            )
        )
        .order_by()
        .values("dog_id")
        .distinct()
    )
    return queryset.filter(
        Q(pk__in=Subquery(managed_ids)) | Q(pk__in=Subquery(source_ids))
    )


def with_card_registration(queryset):
    """Inline first registration label in each dog row instead of an extra SQL round trip.

    List/card templates need only the authority code and number, not complete
    registration objects. The indexed dog_id subquery runs inside the existing
    page/card SELECT, saving one high-latency Supabase request.
    """
    first_registration = (
        DogRegistration.objects.filter(dog_id=OuterRef("pk"))
        .order_by("id")
    )
    return queryset.annotate(
        card_registration_number=Subquery(first_registration.values("number")[:1]),
        card_registration_code=Subquery(first_registration.values("authority__code")[:1]),
    )


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
