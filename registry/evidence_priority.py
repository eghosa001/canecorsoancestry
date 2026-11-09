"""Staff-only, read-only evidence enrichment ranking.

An old moderation approval or source reference is not independently verified
pedigree evidence. No database updates, image imports or inferred identities.
"""
from django.db.models import (
    BooleanField, Case, Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When,
)

from .models import DisputeCase, Dog, DogImage, DogSource, ModerationAudit
from .querysets import published_dogs


PEDIGREE_CONFLICT = (
    Q(sire__sex=Dog.Sex.FEMALE)
    | Q(dam__sex=Dog.Sex.MALE)
    | Q(sire_id__isnull=False, sire_id=F("dam_id"))
    | (
        Q(date_of_birth__isnull=False)
        & (
            Q(sire__date_of_birth__gte=F("date_of_birth"))
            | Q(dam__date_of_birth__gte=F("date_of_birth"))
        )
    )
)


def shared_photo_hashes():
    """A hash shared by two public dogs is only a potential reuse signal.

    Duplicate uploads on a *single* dog alone cannot trigger the review.
    Private and hidden dogs are never used to infer a public-dog alert.
    """
    return (
        DogImage.objects.filter(
            dog__in=published_dogs(), content_sha256__gt="",
        )
        .order_by().values("content_sha256")
        .annotate(dog_count=Count("dog_id", distinct=True))
        .filter(dog_count__gte=2).values("content_sha256")
    )


def annotated_evidence_candidates(queryset):
    sources = DogSource.objects.filter(dog_id=OuterRef("pk"))
    documents = sources.filter(Q(source_url__gt="") | Q(document__gt=""))
    reviewed = documents.filter(verified_at__isnull=False)
    reviewed_parentage = reviewed.filter(
        source_type__in=(DogSource.SourceType.PEDIGREE, DogSource.SourceType.REGISTRY),
    )
    trusted_archive = sources.filter(
        Q(raw_payload__image_url__startswith=(
            "https://canecorsopedigree.com/static/images/animal/"
        ))
        | Q(raw_payload__image_url__startswith=(
            "https://www.canecorsopedigree.com/static/images/animal/"
        ))
    )
    approvals = ModerationAudit.objects.filter(
        action__in=(
            ModerationAudit.Action.SUBMISSION_APPROVED,
            ModerationAudit.Action.VERIFICATION,
            ModerationAudit.Action.SECOND_APPROVAL,
        ),
    ).filter(Q(dog_id=OuterRef("pk")) | Q(submission__dog_id=OuterRef("pk")))
    disputes = DisputeCase.objects.filter(
        dog_id=OuterRef("pk"),
        status__in=(DisputeCase.Status.OPEN, DisputeCase.Status.REVIEWING),
    )
    uploads = DogImage.objects.filter(dog_id=OuterRef("pk"))
    reused = uploads.filter(content_sha256__in=Subquery(shared_photo_hashes()))
    return queryset.annotate(
        priority_has_source_document=Exists(documents),
        priority_has_reviewed_document=Exists(reviewed),
        priority_has_reviewed_parentage=Exists(reviewed_parentage),
        priority_has_approval_audit=Exists(approvals),
        priority_has_dispute=Exists(disputes),
        priority_has_conflict=Case(
            When(PEDIGREE_CONFLICT, then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ),
        priority_has_managed_photo=Exists(uploads),
        priority_has_archive_photo=Exists(trusted_archive),
        priority_has_shared_photo=Exists(reused),
    )


def _points(*, value, **lookup):
    return Case(
        When(then=Value(value), **lookup),
        default=Value(0),
        output_field=IntegerField(),
    )


def prioritized_public_dogs(popular_limit=1000, recent_limit=250):
    """Prioritize 1000 popular + 250 newest public dogs, conflicts and disputes.

    The queue reports cohort size, never presents itself as an exhaustive
    record count. Existing archive-wide filters remain available.
    """
    if not 1 <= popular_limit <= 2000 or not 1 <= recent_limit <= 500:
        raise ValueError("Review cohort size exceeds the safe budget.")

    public = published_dogs()
    popular = public.order_by("-search_count", "pk").values("pk")[:popular_limit]
    recent = public.order_by("-created_at", "pk").values("pk")[:recent_limit]
    disputed = DisputeCase.objects.filter(
        status__in=(DisputeCase.Status.OPEN, DisputeCase.Status.REVIEWING),
    ).order_by().values("dog_id")
    cohort = public.filter(
        Q(pk__in=Subquery(popular))
        | Q(pk__in=Subquery(recent))
        | Q(pk__in=Subquery(disputed))
        | PEDIGREE_CONFLICT
    )
    annotated = annotated_evidence_candidates(cohort)
    need = (
        _points(value=150, priority_has_dispute=True)
        + _points(value=200, priority_has_conflict=True)
        + _points(value=60, priority_has_approval_audit=True, priority_has_reviewed_document=False)
        + _points(value=70, verification_state__in=("identity", "pedigree", "health"), priority_has_reviewed_document=False)
        + _points(value=45, priority_has_source_document=False)
        + _points(value=40, sire_id__isnull=False, dam_id__isnull=False, priority_has_reviewed_parentage=False)
        + _points(value=30, priority_has_shared_photo=True)
        + _points(value=20, priority_has_managed_photo=False, priority_has_archive_photo=False)
        + _points(value=10, sex=Dog.Sex.UNKNOWN)
    )
    annotated = annotated.annotate(priority_need=need).filter(priority_need__gt=0)
    return annotated.annotate(
        priority_score=F("priority_need") + Case(
            When(search_count__gte=1000, then=Value(12)),
            When(search_count__gte=100, then=Value(8)),
            When(search_count__gt=0, then=Value(4)),
            default=Value(0), output_field=IntegerField(),
        )
    )
