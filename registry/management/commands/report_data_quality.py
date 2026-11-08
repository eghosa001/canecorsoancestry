"""Read-only, privacy-safe production database quality metrics.

Published visibility is always determined by registry.querysets.published_dogs.
Counts of attached sources are not independently verified evidence.
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Q

from registry.models import DogImage, DogSource, VerificationState
from registry.querysets import published_dogs


def quality_snapshot():
    public = published_dogs()
    total = public.count()
    with_parents = public.filter(sire_id__isnull=False, dam_id__isnull=False).count()
    with_any_parent = public.filter(Q(sire_id__isnull=False) | Q(dam_id__isnull=False)).count()
    with_photos = DogImage.objects.filter(dog__in=public).values("dog_id").distinct().count()
    with_provenance = (
        DogSource.objects.filter(dog__in=public)
        .filter(Q(source_url__gt="") | Q(document__gt=""))
        .values("dog_id").distinct().count()
    )
    with_reviewed_sources = (
        DogSource.objects.filter(dog__in=public, verified_at__isnull=False)
        .filter(Q(source_url__gt="") | Q(document__gt=""))
        .values("dog_id").distinct().count()
    )
    reviewed_states = public.filter(verification_state__in=(
        VerificationState.IDENTITY_REVIEWED,
        VerificationState.PEDIGREE_REVIEWED,
        VerificationState.HEALTH_VERIFIED,
    )).count()

    def fraction(value):
        return round(100 * value / total, 2) if total else 0.0

    return {
        "public_dogs": total,
        "with_any_recorded_parent": with_any_parent,
        "with_both_recorded_parents": with_parents,
        "with_managed_photo": with_photos,
        "with_source_url_or_document": with_provenance,
        "with_timestamped_reviewed_source": with_reviewed_sources,
        "with_reviewed_dog_status": reviewed_states,
        "percent_with_any_recorded_parent": fraction(with_any_parent),
        "percent_with_both_recorded_parents": fraction(with_parents),
        "percent_with_managed_photo": fraction(with_photos),
        "percent_with_provenance": fraction(with_provenance),
        "percent_with_timestamped_reviewed_source": fraction(with_reviewed_sources),
        "percent_with_reviewed_dog_status": fraction(reviewed_states),
        "disclosure": (
            "Source metadata, an uploaded document, a review timestamp and a "
            "dog verification state are distinct signals. These counts do not "
            "certify independent identity or pedigree accuracy, and exclude "
            "unpublished/private dogs."
        ),
    }


class Command(BaseCommand):
    help = "Report public ancestry completeness without changing records or exposing identities."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(quality_snapshot(), sort_keys=True))
