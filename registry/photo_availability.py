"""Resolve actual local dog photographs without probing a remote bucket per page."""
from collections import defaultdict

from django.conf import settings
from django.core.files.storage import default_storage

from .models import DogImage


def local_media_mode():
    return getattr(settings, "CCA_MEDIA_BACKEND", "") == "oracle-local"


def image_available(name):
    if not name:
        return False
    # Never perform an R2 HTTP HEAD for every card; local stat is inexpensive.
    return not local_media_mode() or default_storage.exists(name)


def attach_card_images(dogs):
    """Prefer the recorded primary; fall back only to the same dog's media."""
    missing = []
    for dog in dogs:
        name = dog.card_image_name
        dog.card_image_url = default_storage.url(name) if image_available(name) else ""
        if not dog.card_image_url and local_media_mode():
            missing.append(dog)
    if not missing:
        return
    alternatives = defaultdict(list)
    for row in DogImage.objects.filter(dog_id__in=[dog.pk for dog in missing]).order_by(
        "dog_id", "-is_primary", "sort_order", "created_at"
    ).values_list("dog_id", "image"):
        alternatives[row[0]].append(row[1])
    for dog in missing:
        for name in alternatives[dog.pk]:
            if image_available(name):
                dog.card_image_url = default_storage.url(name)
                break
