from collections import defaultdict
from datetime import date
import re

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Dog,
    DogAlias,
    DogDocument,
    DogExternalKey,
    DogImage,
    DogRedirect,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    Litter,
    KennelMembership,
    MergeHistory,
    Notification,
    Submission,
    VerificationEvent,
    VerificationState,
)


def unique_dog_slug(name):
    base = slugify(name)[:210] or "dog"
    candidate = base
    suffix = 2
    while Dog.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _json_id(value):
    return str(value) if value else None


def _resolve_dog(value):
    if not value:
        return None
    return Dog.objects.filter(pk=value).first()


def _resolve_litter(value):
    if not value:
        return None
    return Litter.objects.filter(pk=value).first()


def _date_from_payload(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _notify_submission(submission):
    title = f"Submission {submission.get_status_display().lower()}"
    message = (
        f"Your {submission.get_kind_display().lower()} submission "
        f"has been {submission.get_status_display().lower()}."
    )
    Notification.objects.create(
        user=submission.submitted_by,
        title=title,
        message=message,
        link="/member/submissions/",
    )
    if (
        getattr(settings, "ANCESTRY_EMAIL_NOTIFICATIONS", False)
        and submission.submitted_by.email
    ):
        send_mail(
            subject=f"Cane Corso Ancestry · {title}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[submission.submitted_by.email],
            fail_silently=True,
        )


@transaction.atomic
def approve_submission(submission, reviewer, resolution_notes=""):
    submission = Submission.objects.select_for_update().select_related(
        "dog", "kennel", "litter", "document", "submitted_by"
    ).get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can be reviewed.")

    payload = submission.payload or {}

    if submission.kind == Submission.Kind.DOG:
        kennel = submission.kennel
        dog = Dog(
            name=payload["name"].strip(),
            slug=unique_dog_slug(payload["name"]),
            sex=payload.get("sex") or Dog.Sex.UNKNOWN,
            date_of_birth=_date_from_payload(payload.get("date_of_birth")),
            colour=payload.get("colour", "").strip(),
            country=payload.get("country", "").strip(),
            bloodline=payload.get("bloodline", "").strip(),
            kennel=kennel,
            sire=_resolve_dog(payload.get("sire_id")),
            dam=_resolve_dog(payload.get("dam_id")),
            litter=_resolve_litter(payload.get("litter_id")),
            bio=payload.get("bio", "").strip(),
            verification_state=VerificationState.COMMUNITY,
            is_public=False,
        )
        dog.full_clean()
        dog.save()
        submission.dog = dog
        VerificationEvent.objects.create(
            dog=dog,
            state=VerificationState.COMMUNITY,
            reviewer=reviewer,
            note="Created from an approved member submission; remains private until separately published.",
        )

        registration = payload.get("registration", "").strip()
        if registration:
            existing = DogRegistration.objects.filter(
                authority__isnull=True,
                number=registration,
            ).first()
            if existing and existing.dog_id != dog.pk:
                raise ValueError(
                    "That external registration number is already linked to another dog."
                )
            DogRegistration.objects.get_or_create(
                dog=dog,
                authority=None,
                number=registration,
            )

    elif submission.kind == Submission.Kind.CORRECTION:
        dog = submission.dog
        if dog is None:
            raise ValueError("Correction submission has no target dog.")

        editable = ("name", "sex", "date_of_birth", "colour", "country", "bloodline", "bio")
        for field in editable:
            if field in payload:
                value = payload[field]
                if field == "date_of_birth":
                    value = _date_from_payload(value)
                setattr(dog, field, value)

        if "sire_id" in payload:
            dog.sire = _resolve_dog(payload.get("sire_id"))
        if "dam_id" in payload:
            dog.dam = _resolve_dog(payload.get("dam_id"))
        if "litter_id" in payload:
            dog.litter = _resolve_litter(payload.get("litter_id"))
        dog.full_clean()
        dog.save()

        VerificationEvent.objects.create(
            dog=dog,
            state=dog.verification_state,
            reviewer=reviewer,
            note="Moderator approved a member correction submission.",
        )

    elif submission.kind == Submission.Kind.IMAGE:
        if submission.dog is None or not submission.attachment:
            raise ValueError("Image submission requires a target dog and attachment.")
        is_primary = bool(payload.get("is_primary"))
        if is_primary:
            DogImage.objects.filter(dog=submission.dog, is_primary=True).update(
                is_primary=False
            )
        DogImage.objects.create(
            dog=submission.dog,
            image=submission.attachment.name,
            caption=payload.get("caption", "").strip(),
            is_primary=is_primary,
        )

    elif submission.kind == Submission.Kind.DOCUMENT:
        if submission.dog is None or not submission.attachment:
            raise ValueError("Document submission requires a target dog and attachment.")
        DogDocument.objects.create(
            dog=submission.dog,
            title=payload.get("title", "").strip() or "Submitted document",
            document_type=payload.get("document_type", DogDocument.DocumentType.OTHER),
            file=submission.attachment.name,
            is_public=bool(payload.get("is_public")),
            submitted_by=submission.submitted_by,
            source_submission=submission,
        )

    elif submission.kind == Submission.Kind.KENNEL:
        kennel = submission.kennel
        if kennel is None:
            raise ValueError("Kennel submission has no target kennel.")
        for field in ("name", "country", "city", "description", "website"):
            if field in payload:
                setattr(kennel, field, payload[field])
        kennel.save()

    elif submission.kind == Submission.Kind.KENNEL_CLAIM:
        kennel = submission.kennel
        if kennel is None:
            raise ValueError("Kennel claim has no target kennel.")
        if KennelMembership.objects.filter(kennel=kennel).exclude(
            user=submission.submitted_by
        ).exists():
            raise ValueError(
                "This kennel is already linked to another account; resolve ownership manually."
            )
        KennelMembership.objects.update_or_create(
            kennel=kennel,
            user=submission.submitted_by,
            defaults={"role": KennelMembership.Role.OWNER},
        )

    elif submission.kind == Submission.Kind.LITTER_CREATE:
        kennel = submission.kennel
        if kennel is None:
            raise ValueError("Litter submission has no target kennel.")
        code = str(payload.get("code") or "").strip()
        if not code:
            raise ValueError("Litter code is required.")
        if Litter.objects.filter(code=code).exists():
            raise ValueError("A litter with that code already exists.")
        litter = Litter(
            code=code,
            kennel=kennel,
            sire=_resolve_dog(payload.get("sire_id")),
            dam=_resolve_dog(payload.get("dam_id")),
            date_of_birth=_date_from_payload(payload.get("date_of_birth")),
            notes=str(payload.get("notes") or "").strip(),
            is_public=False,
        )
        litter.full_clean()
        litter.save()
        submission.litter = litter

    elif submission.kind == Submission.Kind.LITTER_EDIT:
        litter = submission.litter
        if litter is None:
            raise ValueError("Litter correction has no target litter.")
        code = str(payload.get("code") or litter.code).strip()
        if Litter.objects.exclude(pk=litter.pk).filter(code=code).exists():
            raise ValueError("A litter with that code already exists.")
        litter.code = code
        litter.sire = _resolve_dog(payload.get("sire_id"))
        litter.dam = _resolve_dog(payload.get("dam_id"))
        litter.date_of_birth = _date_from_payload(payload.get("date_of_birth"))
        litter.notes = str(payload.get("notes") or "").strip()
        litter.full_clean()
        litter.save()

    elif submission.kind == Submission.Kind.DOCUMENT_VISIBILITY:
        document = submission.document
        if document is None:
            raise ValueError("Document visibility request has no target document.")
        document.is_public = bool(payload.get("is_public"))
        document.save(update_fields=("is_public",))

    else:
        raise ValueError("Unsupported submission type.")

    submission.status = Submission.Status.APPROVED
    submission.reviewed_by = reviewer
    submission.reviewed_at = timezone.now()
    submission.resolution_notes = resolution_notes
    submission.save(
        update_fields=(
            "dog",
            "litter",
            "status",
            "reviewed_by",
            "reviewed_at",
            "resolution_notes",
            "updated_at",
        )
    )
    _notify_submission(submission)
    return submission


@transaction.atomic
def reject_submission(submission, reviewer, resolution_notes=""):
    submission = Submission.objects.select_for_update().select_related(
        "submitted_by"
    ).get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can be reviewed.")

    submission.status = Submission.Status.REJECTED
    submission.reviewed_by = reviewer
    submission.reviewed_at = timezone.now()
    submission.resolution_notes = resolution_notes
    submission.save(
        update_fields=(
            "status",
            "reviewed_by",
            "reviewed_at",
            "resolution_notes",
            "updated_at",
        )
    )
    _notify_submission(submission)
    return submission


def _move_unique_rows(model, duplicate, canonical, unique_fields):
    moved = 0
    for row in model.objects.filter(dog=duplicate):
        lookup = {"dog": canonical}
        for field in unique_fields:
            lookup[field] = getattr(row, field)
        if model.objects.filter(**lookup).exists():
            row.delete()
        else:
            row.dog = canonical
            row.save(update_fields=("dog",))
            moved += 1
    return moved


@transaction.atomic
def merge_dogs(canonical, duplicate, performed_by=None):
    canonical = Dog.objects.select_for_update().get(pk=canonical.pk)
    duplicate = Dog.objects.select_for_update().get(pk=duplicate.pk)
    if canonical.pk == duplicate.pk:
        raise ValueError("Canonical and duplicate dogs must be different records.")

    retired_id = duplicate.pk
    retired_slug = duplicate.slug
    retired_name = duplicate.name
    summary = {}

    # If a malformed duplicate relationship made the canonical dog its own parent,
    # replace it with the duplicate's real parent where possible.
    if canonical.sire_id == duplicate.pk:
        canonical.sire = (
            duplicate.sire
            if duplicate.sire_id and duplicate.sire_id != canonical.pk
            else None
        )
    if canonical.dam_id == duplicate.pk:
        canonical.dam = (
            duplicate.dam
            if duplicate.dam_id and duplicate.dam_id != canonical.pk
            else None
        )

    for field in (
        "date_of_birth",
        "colour",
        "country",
        "bloodline",
        "kennel",
        "litter",
        "bio",
    ):
        if not getattr(canonical, field) and getattr(duplicate, field):
            setattr(canonical, field, getattr(duplicate, field))

    verification_rank = {
        VerificationState.COMMUNITY: 0,
        VerificationState.SOURCE_ATTACHED: 1,
        VerificationState.IDENTITY_REVIEWED: 2,
        VerificationState.PEDIGREE_REVIEWED: 3,
        VerificationState.HEALTH_VERIFIED: 4,
    }
    if verification_rank.get(duplicate.verification_state, 0) > verification_rank.get(
        canonical.verification_state, 0
    ):
        canonical.verification_state = duplicate.verification_state
    canonical.is_public = canonical.is_public or duplicate.is_public
    canonical.full_clean()
    canonical.save()

    summary["offspring_sire"] = Dog.objects.filter(sire=duplicate).exclude(
        pk=canonical.pk
    ).update(sire=canonical)
    summary["offspring_dam"] = Dog.objects.filter(dam=duplicate).exclude(
        pk=canonical.pk
    ).update(dam=canonical)
    summary["litters_sire"] = Litter.objects.filter(sire=duplicate).update(
        sire=canonical
    )
    summary["litters_dam"] = Litter.objects.filter(dam=duplicate).update(
        dam=canonical
    )

    if retired_name.lower() != canonical.name.lower() and not DogAlias.objects.filter(
        dog=canonical, name__iexact=retired_name
    ).exists():
        DogAlias.objects.create(dog=canonical, name=retired_name)
    for alias in list(DogAlias.objects.filter(dog=duplicate)):
        if DogAlias.objects.filter(dog=canonical, name__iexact=alias.name).exists():
            alias.delete()
        else:
            alias.dog = canonical
            alias.save(update_fields=("dog",))

    summary["external_keys"] = _move_unique_rows(
        DogExternalKey, duplicate, canonical, ("namespace", "key")
    )
    summary["registrations"] = _move_unique_rows(
        DogRegistration, duplicate, canonical, ("authority", "number")
    )
    summary["titles"] = _move_unique_rows(
        DogTitle, duplicate, canonical, ("name",)
    )

    if DogImage.objects.filter(dog=canonical, is_primary=True).exists():
        DogImage.objects.filter(dog=duplicate, is_primary=True).update(is_primary=False)
    summary["images"] = DogImage.objects.filter(dog=duplicate).update(dog=canonical)
    summary["health_records"] = HealthRecord.objects.filter(dog=duplicate).update(
        dog=canonical
    )
    summary["sources"] = DogSource.objects.filter(dog=duplicate).update(dog=canonical)
    summary["documents"] = DogDocument.objects.filter(dog=duplicate).update(
        dog=canonical
    )
    summary["submissions"] = Submission.objects.filter(dog=duplicate).update(
        dog=canonical
    )
    summary["verification_events"] = VerificationEvent.objects.filter(
        dog=duplicate
    ).update(dog=canonical)
    MergeHistory.objects.filter(canonical_dog=duplicate).update(
        canonical_dog=canonical
    )
    DogRedirect.objects.filter(dog=duplicate).update(dog=canonical)
    DogRedirect.objects.update_or_create(
        old_slug=retired_slug, defaults={"dog": canonical}
    )

    history = MergeHistory.objects.create(
        canonical_dog=canonical,
        retired_dog_id=retired_id,
        retired_slug=retired_slug,
        retired_name=retired_name,
        performed_by=performed_by,
        summary=summary,
    )
    duplicate.delete()
    return history



def duplicate_candidates(limit=30):
    """Return conservative duplicate suggestions without mutating any records."""
    dogs = list(
        Dog.objects.prefetch_related("registrations").order_by("name")
    )
    name_buckets = defaultdict(list)
    registration_buckets = defaultdict(list)

    for dog in dogs:
        normalized = re.sub(r"[^a-z0-9]+", "", dog.name.lower())
        if normalized:
            name_buckets[normalized].append(dog)
        for registration in dog.registrations.all():
            number = re.sub(r"\s+", "", registration.number.lower())
            authority = registration.authority_id or "none"
            if number:
                registration_buckets[(authority, number)].append(dog)

    pairs = {}

    def add_pair(left, right, reason):
        if left.pk == right.pk:
            return
        ordered = sorted((left, right), key=lambda item: str(item.pk))
        key = (ordered[0].pk, ordered[1].pk)
        entry = pairs.setdefault(
            key,
            {"left": ordered[0], "right": ordered[1], "reasons": []},
        )
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    for bucket in name_buckets.values():
        if len(bucket) > 1:
            for index, left in enumerate(bucket):
                for right in bucket[index + 1 :]:
                    add_pair(left, right, "Same normalized name")

    for bucket in registration_buckets.values():
        if len(bucket) > 1:
            for index, left in enumerate(bucket):
                for right in bucket[index + 1 :]:
                    add_pair(left, right, "Same external registration")

    return list(pairs.values())[:limit]
