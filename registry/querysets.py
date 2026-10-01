from django.db.models import Exists, F, OuterRef, Window
from django.db.models.functions import Coalesce, RowNumber

from .models import DogImage


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
