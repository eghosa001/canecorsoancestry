from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
import re

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Dog,
    DogAlias,
    DogDocument,
    DogExternalKey,
    DogIdentityNumber,
    DogImage,
    DogRedirect,
    DogRegistration,
    DogSource,
    DogTitle,
    DisputeCase,
    EvidenceRequest,
    HealthRecord,
    Kennel,
    Litter,
    KennelMembership,
    MergeHistory,
    ModerationAudit,
    Notification,
    Submission,
    SubmissionEvidence,
    SubmissionReview,
    SubmissionRiskLevel,
    SubmissionVerificationStatus,
    VerificationEvent,
    VerificationState,
)
from .permissions import can_review_flagged_submissions, can_review_submissions, can_second_approve
from .verification import verification_snapshot, verify_submission


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
    try:
        return Dog.objects.filter(pk=value).first()
    except (TypeError, ValueError, ValidationError):
        return None


def _resolve_litter(value):
    if not value:
        return None
    try:
        return Litter.objects.filter(pk=value).first()
    except (TypeError, ValueError, ValidationError):
        return None


def _canonical_litter_conflict(*, sire, dam, date_of_birth, exclude_litter_id=None):
    """Serialize canonical-litter checks on the parent rows.

    When both parents and DOB are known, the biological birth event is unique.
    Locking the same ordered parent rows makes concurrent moderation approvals
    serialize even before a database-level uniqueness constraint is involved.
    """
    if not (sire and dam and date_of_birth):
        return None

    parent_ids = sorted((sire.pk, dam.pk), key=str)
    # Force lock acquisition now and in a stable order to avoid deadlocks.
    list(
        Dog.objects.select_for_update()
        .filter(pk__in=parent_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    conflicts = Litter.objects.filter(
        sire=sire,
        dam=dam,
        date_of_birth=date_of_birth,
    )
    if exclude_litter_id:
        conflicts = conflicts.exclude(pk=exclude_litter_id)
    return conflicts.order_by("created_at", "pk").first()


def _date_from_payload(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def record_audit(
    *,
    action,
    actor=None,
    dog=None,
    kennel=None,
    litter=None,
    submission=None,
    dispute=None,
    summary=None,
    note="",
):
    return ModerationAudit.objects.create(
        action=action,
        actor=actor,
        dog=dog,
        kennel=kennel,
        litter=litter,
        submission=submission,
        dispute=dispute,
        summary=summary or {},
        note=note,
    )


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


def _require_paid_submission(submission):
    payload = submission.payload or {}
    if not payload.get("_paid_submission"):
        return None

    from accounts.models import PaymentSubmissionLink, SubmissionPayment

    try:
        link = PaymentSubmissionLink.objects.select_related(
            "payment", "payment__kennel"
        ).get(submission=submission)
    except PaymentSubmissionLink.DoesNotExist as exc:
        raise ValueError(
            "This submission requires a paid Paystack package before approval."
        ) from exc

    payment = link.payment
    if payment.status != SubmissionPayment.Status.PAID:
        raise ValueError("This submission's Paystack payment is not confirmed.")
    if payment.user_id != submission.submitted_by_id:
        raise ValueError("The payment belongs to a different member.")
    if payment.kennel_id != submission.kennel_id:
        raise ValueError("The payment belongs to a different kennel.")
    if submission.kennel is None or not submission.kennel.verified_at:
        raise ValueError("The kennel must be moderator-verified before publication.")
    if not KennelMembership.objects.filter(
        kennel=submission.kennel,
        user=submission.submitted_by,
        role__in=[KennelMembership.Role.OWNER, KennelMembership.Role.EDITOR],
    ).exists():
        raise ValueError(
            "The submitting kennel owner/editor must be verified before publication."
        )

    if submission.kind == Submission.Kind.DOG:
        if payload.get("litter_submission_id"):
            if (
                link.slot_kind != PaymentSubmissionLink.SlotKind.PUPPY
                or payment.package != SubmissionPayment.Package.LITTER
            ):
                raise ValueError("This puppy is not linked to a paid litter package.")
        else:
            if link.slot_kind != PaymentSubmissionLink.SlotKind.DOG:
                raise ValueError("This dog is not linked to a dog payment slot.")
            if payment.package not in {
                SubmissionPayment.Package.SINGLE_DOG,
                SubmissionPayment.Package.MULTI_DOG,
            }:
                raise ValueError("This dog slot is backed by the wrong payment package.")
    elif submission.kind == Submission.Kind.LITTER_CREATE:
        if (
            link.slot_kind != PaymentSubmissionLink.SlotKind.LITTER
            or payment.package != SubmissionPayment.Package.LITTER
        ):
            raise ValueError("This litter is not linked to a paid litter package.")

    return link


def _review_evidence_snapshot(submission):
    return [
        {
            "id": str(item.pk),
            "type": item.evidence_type,
            "sha256": item.sha256,
            "uploaded_by": item.uploaded_by_display_label,
            "created_at": item.created_at.isoformat(),
        }
        for item in submission.verification_evidence.select_related("uploaded_by").all()
    ]


def _create_review(submission, reviewer, action, reason=""):
    return SubmissionReview.objects.create(
        submission=submission,
        reviewer=reviewer,
        action=action,
        reason=reason,
        warnings_snapshot=verification_snapshot(submission),
        evidence_snapshot=_review_evidence_snapshot(submission),
    )


@transaction.atomic
def request_submission_evidence(submission, reviewer, reason):
    if not can_review_submissions(reviewer):
        raise ValueError("This account does not have submission-review authority.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Explain what evidence is required.")
    submission = Submission.objects.select_for_update().get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can request evidence.")
    evidence_request = EvidenceRequest.objects.create(
        submission=submission,
        requested_by=reviewer,
        note=reason,
    )
    submission.verification_status = SubmissionVerificationStatus.AWAITING_EVIDENCE
    submission.save(update_fields=("verification_status", "updated_at"))
    _create_review(
        submission,
        reviewer,
        SubmissionReview.Action.EVIDENCE_REQUESTED,
        reason,
    )
    Notification.objects.create(
        user=submission.submitted_by,
        title="Verification evidence requested",
        message=reason,
        link="/member/submissions/",
    )
    record_audit(
        action=ModerationAudit.Action.EVIDENCE_REQUESTED,
        actor=reviewer,
        dog=submission.dog,
        kennel=submission.kennel,
        litter=submission.litter,
        submission=submission,
        summary={"evidence_request_id": str(evidence_request.pk), "warnings": verification_snapshot(submission)},
        note=reason,
    )
    return evidence_request


@transaction.atomic
def request_high_risk_override(submission, reviewer, reason):
    if not can_review_flagged_submissions(reviewer):
        raise ValueError("Only a Senior Moderator or Super Admin can request a high-risk override.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("An override reason is required.")
    submission = Submission.objects.select_for_update().get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can be overridden.")
    verify_submission(submission, audit=False)
    submission.refresh_from_db()
    if not submission.requires_second_review:
        raise ValueError("This submission does not require a second approval.")
    review = _create_review(
        submission,
        reviewer,
        SubmissionReview.Action.OVERRIDE_REQUESTED,
        reason,
    )
    submission.verification_status = SubmissionVerificationStatus.AWAITING_SECOND
    submission.requires_second_review = True
    submission.save(
        update_fields=(
            "verification_status",
            "requires_second_review",
            "updated_at",
        )
    )
    record_audit(
        action=ModerationAudit.Action.OVERRIDE_REQUESTED,
        actor=reviewer,
        dog=submission.dog,
        kennel=submission.kennel,
        litter=submission.litter,
        submission=submission,
        summary={"review_id": str(review.pk), "warnings": review.warnings_snapshot, "evidence": review.evidence_snapshot},
        note=reason,
    )
    return review


@transaction.atomic
def reject_high_risk_override(submission, reviewer, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A second-review rejection reason is required.")
    submission = Submission.objects.select_for_update().get(pk=submission.pk)
    pending_override = submission.review_decisions.filter(
        action=SubmissionReview.Action.OVERRIDE_REQUESTED
    ).order_by("-created_at").first()
    if pending_override is None:
        raise ValueError("No high-risk override is awaiting second review.")
    if pending_override.reviewer_id == reviewer.pk:
        raise ValueError("The second reviewer must be a different Senior Moderator or Super Admin.")
    if not can_second_approve(reviewer):
        raise ValueError("Only a Senior Moderator or Super Admin can complete second review.")
    _create_review(
        submission,
        reviewer,
        SubmissionReview.Action.SECOND_REJECTED,
        reason,
    )
    submission.verification_status = SubmissionVerificationStatus.REVIEW
    submission.save(update_fields=("verification_status", "updated_at"))
    record_audit(
        action=ModerationAudit.Action.SECOND_APPROVAL,
        actor=reviewer,
        dog=submission.dog,
        kennel=submission.kennel,
        litter=submission.litter,
        submission=submission,
        summary={
            "decision": "override_rejected",
            "first_reviewer_admin_number": pending_override.reviewer_admin_number_snapshot,
        },
        note=reason,
    )
    return submission


@transaction.atomic
def approve_submission(
    submission,
    reviewer,
    resolution_notes="",
    *,
    allow_override=False,
    override_review=None,
):
    if not can_review_submissions(reviewer):
        raise ValueError("This account does not have submission-review authority.")
    submission = Submission.objects.select_for_update(of=("self",)).select_related(
        "dog", "kennel", "litter", "document", "submitted_by"
    ).get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can be reviewed.")

    # Payment/package eligibility is a hard server-side prerequisite and is
    # never overrideable by moderation. Run it before warning/override logic.
    paid_link = _require_paid_submission(submission)

    findings = verify_submission(submission, audit=False)
    blocking_findings = [
        finding
        for finding in findings
        if finding.risk_level != SubmissionRiskLevel.GREEN
    ]
    submission.refresh_from_db()
    resolution_notes = (resolution_notes or "").strip()
    if blocking_findings:
        if allow_override and not can_review_flagged_submissions(reviewer):
            raise ValueError("Only a Senior Moderator or Super Admin can override automated warnings.")
        if not allow_override:
            raise ValueError(
                "Automated verification warnings are present. Use Approve with override and provide a reason."
            )
        if not resolution_notes:
            raise ValueError("An override reason is required.")
        if submission.requires_second_review:
            if override_review is None:
                raise ValueError("High-risk findings require a second Senior Moderator or Super Admin.")
            if (
                override_review.submission_id != submission.pk
                or override_review.action != SubmissionReview.Action.OVERRIDE_REQUESTED
            ):
                raise ValueError("The high-risk override request is invalid.")
            if override_review.reviewer_id == reviewer.pk:
                raise ValueError("The second reviewer must be a different Senior Moderator or Super Admin.")
            if not can_second_approve(reviewer):
                raise ValueError("Only a Senior Moderator or Super Admin can complete second review.")

    payload = submission.payload or {}
    review_diff = submission_diff(submission)

    if submission.kind == Submission.Kind.DOG:
        kennel = submission.kennel
        sire = _resolve_dog(payload.get("sire_id"))
        dam = _resolve_dog(payload.get("dam_id"))
        litter = _resolve_litter(payload.get("litter_id"))
        date_of_birth = _date_from_payload(payload.get("date_of_birth"))

        litter_submission_id = payload.get("litter_submission_id")
        if litter_submission_id:
            from accounts.models import PaymentSubmissionLink

            litter_submission = Submission.objects.select_related(
                "litter", "kennel"
            ).filter(
                pk=litter_submission_id,
                kind=Submission.Kind.LITTER_CREATE,
                status=Submission.Status.APPROVED,
            ).first()
            if litter_submission is None or litter_submission.litter is None:
                raise ValueError(
                    "Approve the litter record before approving puppies from that litter."
                )
            litter_payment_link = PaymentSubmissionLink.objects.filter(
                submission=litter_submission
            ).first()
            if (
                paid_link is None
                or litter_payment_link is None
                or litter_payment_link.payment_id != paid_link.payment_id
            ):
                raise ValueError("The puppy and litter must use the same paid litter package.")
            litter = litter_submission.litter
            kennel = litter.kennel
            sire = litter.sire
            dam = litter.dam
            date_of_birth = litter.date_of_birth

        verification_state = (
            VerificationState.PEDIGREE_REVIEWED
            if sire or dam
            else VerificationState.IDENTITY_REVIEWED
        )
        dog = Dog(
            name=payload["name"].strip(),
            slug=unique_dog_slug(payload["name"]),
            sex=payload.get("sex") or Dog.Sex.UNKNOWN,
            date_of_birth=date_of_birth,
            colour=payload.get("colour", "").strip(),
            country=payload.get("country", "").strip(),
            bloodline=payload.get("bloodline", "").strip(),
            kennel=kennel,
            sire=sire,
            dam=dam,
            litter=litter,
            bio=payload.get("bio", "").strip(),
            verification_state=verification_state,
            is_public=True,
        )
        dog.full_clean()
        dog.save()
        submission.dog = dog
        VerificationEvent.objects.create(
            dog=dog,
            state=verification_state,
            reviewer=reviewer,
            note="Created and published after moderator verification of the submitted record.",
        )

        registration = payload.get("registration", "").strip()
        if registration:
            existing = DogRegistration.objects.filter(
                number__iexact=registration,
            ).first()
            if existing and existing.dog_id != dog.pk:
                raise ValueError(
                    "That external registration number is already linked to another dog. Resolve or merge the identity instead of creating a duplicate registration."
                )
            DogRegistration.objects.get_or_create(
                dog=dog,
                authority=None,
                number=registration,
            )

        microchip = str(payload.get("microchip_number") or "").strip()
        if microchip:
            normalized_chip = re.sub(r"[^A-Za-z0-9]+", "", microchip).upper()
            existing_chip = DogIdentityNumber.objects.filter(
                kind=DogIdentityNumber.Kind.MICROCHIP,
                normalized_value=normalized_chip,
            ).first()
            if existing_chip and existing_chip.dog_id != dog.pk:
                raise ValueError(
                    "That microchip is already linked to another canonical dog. Resolve the identity conflict first."
                )
            DogIdentityNumber.objects.get_or_create(
                dog=dog,
                kind=DogIdentityNumber.Kind.MICROCHIP,
                normalized_value=normalized_chip,
                defaults={"value": microchip},
            )

        if submission.attachment:
            DogImage.objects.create(
                dog=dog,
                image=submission.attachment.name,
                caption=str(payload.get("photo_caption") or "").strip(),
                content_sha256=str(payload.get("photo_sha256") or "").strip(),
                is_primary=True,
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

        if "registration" in payload:
            desired_registration = str(payload.get("registration") or "").strip()
            current_registration = dog.registrations.filter(
                authority__isnull=True
            ).first()
            if desired_registration:
                conflict = DogRegistration.objects.filter(
                    number__iexact=desired_registration
                ).exclude(dog=dog).first()
                if conflict:
                    raise ValueError(
                        "That registration number is already linked to another canonical dog. Resolve the identity conflict first."
                    )
                if current_registration:
                    current_registration.number = desired_registration
                    current_registration.save(update_fields=("number",))
                else:
                    DogRegistration.objects.create(
                        dog=dog,
                        authority=None,
                        number=desired_registration,
                    )
            elif current_registration:
                current_registration.delete()

        if "microchip_number" in payload:
            desired_microchip = str(payload.get("microchip_number") or "").strip()
            current_microchip = dog.identity_numbers.filter(
                kind=DogIdentityNumber.Kind.MICROCHIP
            ).first()
            if desired_microchip:
                normalized_chip = re.sub(
                    r"[^A-Za-z0-9]+", "", desired_microchip
                ).upper()
                conflict = DogIdentityNumber.objects.filter(
                    kind=DogIdentityNumber.Kind.MICROCHIP,
                    normalized_value=normalized_chip,
                ).exclude(dog=dog).first()
                if conflict:
                    raise ValueError(
                        "That microchip is already linked to another canonical dog. Resolve the identity conflict first."
                    )
                if current_microchip:
                    current_microchip.value = desired_microchip
                    current_microchip.save()
                else:
                    DogIdentityNumber.objects.create(
                        dog=dog,
                        kind=DogIdentityNumber.Kind.MICROCHIP,
                        value=desired_microchip,
                    )
            elif current_microchip:
                current_microchip.delete()

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
            content_sha256=str(payload.get("sha256") or "").strip(),
            is_primary=is_primary,
        )

    elif submission.kind == Submission.Kind.HEALTH:
        if submission.dog is None or not submission.attachment:
            raise ValueError("Health/DNA submission requires a target dog and supporting evidence.")

        test_type = str(payload.get("test_type") or "").strip()
        result = str(payload.get("result") or "").strip()
        if not test_type or not result:
            raise ValueError("Health/DNA submissions require both a test name and result.")

        health_record = HealthRecord.objects.create(
            dog=submission.dog,
            test_type=test_type,
            result=result,
            tested_on=_date_from_payload(payload.get("tested_on")),
            verification_state=VerificationState.HEALTH_VERIFIED,
            notes=submission.notes,
        )
        evidence_type = str(payload.get("evidence_type") or "health")
        document_type = (
            DogDocument.DocumentType.DNA
            if evidence_type == "dna"
            else DogDocument.DocumentType.HEALTH
        )
        DogDocument.objects.create(
            dog=submission.dog,
            title=f"{test_type} supporting evidence",
            document_type=document_type,
            file=submission.attachment.name,
            is_public=False,
            submitted_by=submission.submitted_by,
            source_submission=submission,
        )
        VerificationEvent.objects.create(
            dog=submission.dog,
            health_record=health_record,
            state=VerificationState.HEALTH_VERIFIED,
            reviewer=reviewer,
            note="Health/DNA result verified from member-supplied supporting evidence.",
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

    elif submission.kind == Submission.Kind.KENNEL_CREATE:
        name = str(payload.get("name") or "").strip()
        kennel_slug = str(payload.get("slug") or slugify(name)[:190]).strip()
        if not name or not kennel_slug:
            raise ValueError("Kennel name is required.")
        if Kennel.objects.filter(
            Q(name__iexact=name) | Q(slug__iexact=kennel_slug)
        ).exists():
            raise ValueError(
                "That kennel or breeder brand already exists. Link the member to the existing profile instead."
            )
        try:
            with transaction.atomic():
                kennel = Kennel.objects.create(
                    name=name,
                    slug=kennel_slug,
                    country=str(payload.get("country") or "").strip(),
                    city=str(payload.get("city") or "").strip(),
                    description=str(payload.get("description") or "").strip(),
                    website=str(payload.get("website") or "").strip(),
                    verified_at=timezone.now(),
                )
        except IntegrityError as exc:
            raise ValueError(
                "That kennel or breeder brand name is already in use."
            ) from exc
        submission.kennel = kennel
        KennelMembership.objects.create(
            kennel=kennel,
            user=submission.submitted_by,
            role=KennelMembership.Role.OWNER,
        )

    elif submission.kind == Submission.Kind.KENNEL:
        kennel = submission.kennel
        if kennel is None:
            raise ValueError("Kennel submission has no target kennel.")
        for field in ("name", "country", "city", "description", "website"):
            if field in payload:
                setattr(kennel, field, payload[field])
        kennel.verified_at = timezone.now()
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
        if not kennel.verified_at:
            kennel.verified_at = timezone.now()
            kennel.save(update_fields=("verified_at", "updated_at"))

    elif submission.kind == Submission.Kind.LITTER_CREATE:
        kennel = submission.kennel
        if kennel is None:
            raise ValueError("Litter submission has no target kennel.")
        code = str(payload.get("code") or "").strip()
        if not code:
            raise ValueError("Litter code is required.")
        if Litter.objects.filter(code=code).exists():
            raise ValueError("A litter with that code already exists.")

        sire = _resolve_dog(payload.get("sire_id"))
        dam = _resolve_dog(payload.get("dam_id"))
        date_of_birth = _date_from_payload(payload.get("date_of_birth"))
        existing_litter = _canonical_litter_conflict(
            sire=sire,
            dam=dam,
            date_of_birth=date_of_birth,
        )
        if existing_litter is not None:
            raise ValueError(
                "This sire, dam and date of birth already identify one canonical "
                f"litter ({existing_litter.public_label}). Use the existing litter "
                "instead of creating another."
            )

        litter = Litter(
            code=code,
            kennel=kennel,
            sire=sire,
            dam=dam,
            date_of_birth=date_of_birth,
            country=str(payload.get("country") or "").strip(),
            declared_puppy_count=payload.get("declared_puppy_count") or None,
            notes=str(payload.get("notes") or "").strip(),
            is_public=True,
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

        sire = _resolve_dog(payload.get("sire_id"))
        dam = _resolve_dog(payload.get("dam_id"))
        date_of_birth = _date_from_payload(payload.get("date_of_birth"))
        existing_litter = _canonical_litter_conflict(
            sire=sire,
            dam=dam,
            date_of_birth=date_of_birth,
            exclude_litter_id=litter.pk,
        )
        if existing_litter is not None:
            raise ValueError(
                "This sire, dam and date of birth already identify one canonical "
                f"litter ({existing_litter.public_label}). Merge/correct the existing "
                "record instead of creating a duplicate birth event."
            )

        litter.code = code
        litter.sire = sire
        litter.dam = dam
        litter.date_of_birth = date_of_birth
        litter.country = str(payload.get("country") or "").strip()
        litter.declared_puppy_count = payload.get("declared_puppy_count") or None
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
            "kennel",
            "litter",
            "status",
            "reviewed_by",
            "reviewed_at",
            "resolution_notes",
            "updated_at",
        )
    )
    review_action = SubmissionReview.Action.APPROVED
    if blocking_findings and submission.requires_second_review:
        review_action = SubmissionReview.Action.SECOND_APPROVED
    elif blocking_findings:
        review_action = SubmissionReview.Action.OVERRIDE_APPROVED
    final_review = _create_review(
        submission,
        reviewer,
        review_action,
        resolution_notes,
    )
    _notify_submission(submission)
    record_audit(
        action=ModerationAudit.Action.SUBMISSION_APPROVED,
        actor=reviewer,
        dog=submission.dog,
        kennel=submission.kennel,
        litter=submission.litter,
        submission=submission,
        summary={
            "kind": submission.kind,
            "changes": review_diff,
            "warnings": final_review.warnings_snapshot,
            "evidence": final_review.evidence_snapshot,
            "review_action": final_review.action,
            "first_override_reviewer_admin_number": (
                override_review.reviewer_admin_number_snapshot
                if override_review is not None
                else None
            ),
            "second_reviewer_admin_number": (
                final_review.reviewer_admin_number_snapshot
                if final_review.action == SubmissionReview.Action.SECOND_APPROVED
                else None
            ),
        },
        note=resolution_notes,
    )
    if final_review.action == SubmissionReview.Action.SECOND_APPROVED:
        record_audit(
            action=ModerationAudit.Action.SECOND_APPROVAL,
            actor=reviewer,
            dog=submission.dog,
            kennel=submission.kennel,
            litter=submission.litter,
            submission=submission,
            summary={
                "decision": "approved",
                "first_reviewer_admin_number": override_review.reviewer_admin_number_snapshot,
                "second_reviewer_admin_number": final_review.reviewer_admin_number_snapshot,
                "warnings": final_review.warnings_snapshot,
                "evidence": final_review.evidence_snapshot,
            },
            note=resolution_notes,
        )
    if submission.kind in {Submission.Kind.CORRECTION, Submission.Kind.LITTER_EDIT} and review_diff:
        record_audit(
            action=ModerationAudit.Action.RECORD_CHANGED,
            actor=reviewer,
            dog=submission.dog,
            kennel=submission.kennel,
            litter=submission.litter,
            submission=submission,
            summary={
                "changes": review_diff,
                "warnings": final_review.warnings_snapshot,
                "review_action": final_review.action,
            },
            note=resolution_notes,
        )
    return submission


@transaction.atomic
def reject_submission(submission, reviewer, resolution_notes=""):
    if not can_review_submissions(reviewer):
        raise ValueError("This account does not have submission-review authority.")
    submission = Submission.objects.select_for_update().select_related(
        "submitted_by"
    ).get(pk=submission.pk)
    if submission.status != Submission.Status.PENDING:
        raise ValueError("Only pending submissions can be reviewed.")

    findings = verify_submission(submission, audit=False)
    blocking_findings = [
        finding
        for finding in findings
        if finding.risk_level != SubmissionRiskLevel.GREEN
    ]
    submission.refresh_from_db()
    if blocking_findings and not can_review_flagged_submissions(reviewer):
        raise ValueError("A Senior Moderator or Super Admin must decide a flagged submission.")
    review_diff = submission_diff(submission)
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
    final_review = _create_review(
        submission,
        reviewer,
        SubmissionReview.Action.REJECTED,
        resolution_notes,
    )
    _notify_submission(submission)
    record_audit(
        action=ModerationAudit.Action.SUBMISSION_REJECTED,
        actor=reviewer,
        dog=submission.dog,
        kennel=submission.kennel,
        litter=submission.litter,
        submission=submission,
        summary={
            "kind": submission.kind,
            "changes": review_diff,
            "warnings": final_review.warnings_snapshot,
            "evidence": final_review.evidence_snapshot,
        },
        note=resolution_notes,
    )
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


def _is_ancestor(ancestor_id, dog_id):
    if not ancestor_id or not dog_id or ancestor_id == dog_id:
        return bool(ancestor_id and dog_id and ancestor_id == dog_id)
    frontier = {dog_id}
    seen = set()
    while frontier:
        unseen = frontier - seen
        if not unseen:
            return False
        seen.update(unseen)
        next_frontier = set()
        for sire_id, dam_id in Dog.objects.filter(pk__in=unseen).values_list(
            "sire_id", "dam_id"
        ):
            if sire_id == ancestor_id or dam_id == ancestor_id:
                return True
            if sire_id:
                next_frontier.add(sire_id)
            if dam_id:
                next_frontier.add(dam_id)
        frontier = next_frontier
    return False


@transaction.atomic
def merge_dogs(canonical, duplicate, performed_by=None):
    canonical = Dog.objects.select_for_update().get(pk=canonical.pk)
    duplicate = Dog.objects.select_for_update().get(pk=duplicate.pk)
    if canonical.pk == duplicate.pk:
        raise ValueError("Canonical and duplicate dogs must be different records.")
    if _is_ancestor(canonical.pk, duplicate.pk) or _is_ancestor(
        duplicate.pk, canonical.pk
    ):
        raise ValueError(
            "Cannot merge dogs that are connected as ancestor and descendant. "
            "Resolve the pedigree relationship first."
        )

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
    record_audit(
        action=ModerationAudit.Action.DOG_MERGED,
        actor=performed_by,
        dog=canonical,
        kennel=canonical.kennel,
        summary={
            "retired_dog_id": str(retired_id),
            "retired_slug": retired_slug,
            "retired_name": retired_name,
            "moved": summary,
        },
    )
    duplicate.delete()
    return history




def _display_value(value):
    if value is None or value == "":
        return "Not recorded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dog_name(value):
    dog = _resolve_dog(value)
    return dog.name if dog else "Not recorded"


def _litter_name(value):
    litter = _resolve_litter(value)
    return litter.code if litter else "Not recorded"


def submission_diff(submission, *, dog_names=None, litter_names=None):
    """Return moderator-friendly before/after changes without mutating the target.

    Optional lookup maps let queue/list callers batch-reference related records
    instead of issuing one lookup query per payload field.
    """
    payload = submission.payload or {}
    changes = []

    def add(label, before, after):
        before_text = _display_value(before)
        after_text = _display_value(after)
        if before_text != after_text:
            changes.append(
                {"field": label, "before": before_text, "after": after_text}
            )

    def dog_name(value):
        if dog_names is None:
            return _dog_name(value)
        return dog_names.get(str(value), "Not recorded") if value else "Not recorded"

    def litter_name(value):
        if litter_names is None:
            return _litter_name(value)
        return litter_names.get(str(value), "Not recorded") if value else "Not recorded"

    if submission.kind == Submission.Kind.CORRECTION and submission.dog:
        dog = submission.dog
        field_map = (
            ("Name", "name"),
            ("Sex", "sex"),
            ("Date of birth", "date_of_birth"),
            ("Colour", "colour"),
            ("Country", "country"),
            ("Bloodline", "bloodline"),
            ("Biography", "bio"),
        )
        for label, field in field_map:
            if field in payload:
                add(label, getattr(dog, field), payload.get(field))
        if "sire_id" in payload:
            add("Sire", dog.sire.name if dog.sire else None, dog_name(payload.get("sire_id")))
        if "dam_id" in payload:
            add("Dam", dog.dam.name if dog.dam else None, dog_name(payload.get("dam_id")))
        if "litter_id" in payload:
            add(
                "Litter",
                dog.litter.code if dog.litter else None,
                litter_name(payload.get("litter_id")),
            )
        if "registration" in payload:
            current_registration = dog.registrations.filter(authority__isnull=True).first()
            add(
                "Registration number",
                current_registration.number if current_registration else None,
                payload.get("registration"),
            )
        if "microchip_number" in payload:
            current_microchip = dog.identity_numbers.filter(
                kind=DogIdentityNumber.Kind.MICROCHIP
            ).first()
            add(
                "Microchip number",
                current_microchip.value if current_microchip else None,
                payload.get("microchip_number"),
            )

    elif submission.kind == Submission.Kind.KENNEL and submission.kennel:
        for label, field in (
            ("Name", "name"),
            ("Country", "country"),
            ("City", "city"),
            ("Description", "description"),
            ("Website", "website"),
        ):
            if field in payload:
                add(label, getattr(submission.kennel, field), payload.get(field))

    elif submission.kind == Submission.Kind.LITTER_EDIT and submission.litter:
        litter = submission.litter
        add("Code", litter.code, payload.get("code"))
        add("Sire", litter.sire.name if litter.sire else None, dog_name(payload.get("sire_id")))
        add("Dam", litter.dam.name if litter.dam else None, dog_name(payload.get("dam_id")))
        add("Date of birth", litter.date_of_birth, payload.get("date_of_birth"))
        add("Country", litter.country, payload.get("country"))
        add("Declared puppy count", litter.declared_puppy_count, payload.get("declared_puppy_count"))
        add("Notes", litter.notes, payload.get("notes"))

    elif submission.kind == Submission.Kind.DOCUMENT_VISIBILITY and submission.document:
        add(
            "Document visibility",
            "Public" if submission.document.is_public else "Private",
            "Public" if bool(payload.get("is_public")) else "Private",
        )

    elif submission.kind in {
        Submission.Kind.DOG,
        Submission.Kind.LITTER_CREATE,
        Submission.Kind.KENNEL_CREATE,
        Submission.Kind.KENNEL_CLAIM,
        Submission.Kind.DOCUMENT,
        Submission.Kind.HEALTH,
        Submission.Kind.IMAGE,
    }:
        for key, value in payload.items():
            label = key.replace("_id", "").replace("_", " ").title()
            if key in {"sire_id", "dam_id"}:
                value = dog_name(value)
            elif key == "litter_id":
                value = litter_name(value)
            changes.append(
                {"field": label, "before": "New record", "after": _display_value(value)}
            )

    return changes


def _normalized_name(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _registration_keys(dog):
    return {
        (registration.authority_id or "none", re.sub(r"\s+", "", registration.number.lower()))
        for registration in dog.registrations.all()
        if registration.number
    }


def _score_duplicate_pair(reference, candidate, trigram_score=None):
    reasons = []
    score = 0.0

    left_name = _normalized_name(reference.name)
    right_name = _normalized_name(candidate.name)
    ratio = SequenceMatcher(None, left_name, right_name).ratio() if left_name and right_name else 0

    if left_name and left_name == right_name:
        score += 60
        reasons.append("Same normalized name")
    else:
        name_score = max(ratio, trigram_score or 0) * 45
        score += name_score
        if name_score >= 28:
            reasons.append(f"Similar name ({max(ratio, trigram_score or 0):.0%})")

    shared_registrations = _registration_keys(reference) & _registration_keys(candidate)
    if shared_registrations:
        score += 55
        reasons.append("Same external registration")

    if reference.sire_id and reference.sire_id == candidate.sire_id:
        score += 14
        reasons.append("Same sire")
    if reference.dam_id and reference.dam_id == candidate.dam_id:
        score += 14
        reasons.append("Same dam")
    if reference.date_of_birth and reference.date_of_birth == candidate.date_of_birth:
        score += 10
        reasons.append("Same date of birth")
    if reference.kennel_id and reference.kennel_id == candidate.kennel_id:
        score += 6
        reasons.append("Same kennel")
    if reference.sex != Dog.Sex.UNKNOWN and reference.sex == candidate.sex:
        score += 3
    elif (
        reference.sex != Dog.Sex.UNKNOWN
        and candidate.sex != Dog.Sex.UNKNOWN
        and reference.sex != candidate.sex
    ):
        score -= 18
        reasons.append("Conflicting sex")

    score = max(0, min(100, round(score)))
    if score >= 80:
        confidence = "High"
    elif score >= 60:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "reference": reference,
        "candidate": candidate,
        "left": reference,
        "right": candidate,
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
    }


def duplicate_matches(reference, limit=20):
    """Find likely duplicate records, using pg_trgm on PostgreSQL when available."""
    queryset = (
        Dog.objects.exclude(pk=reference.pk)
        .select_related("sire", "dam", "kennel")
        .prefetch_related("registrations")
    )

    trigram_lookup = {}
    if connection.vendor == "postgresql":
        reference_numbers = [
            registration.number
            for registration in reference.registrations.all()
            if registration.number
        ]
        queryset = queryset.annotate(
            name_similarity=TrigramSimilarity("name", reference.name)
        ).filter(
            Q(name_similarity__gte=0.18)
            | Q(registrations__number__in=reference_numbers)
        ).distinct().order_by("-name_similarity")[:120]
        candidates = list(queryset)
        trigram_lookup = {
            dog.pk: float(getattr(dog, "name_similarity", 0) or 0)
            for dog in candidates
        }
    else:
        candidates = list(queryset[:1000])

    results = []
    for candidate in candidates:
        row = _score_duplicate_pair(
            reference,
            candidate,
            trigram_score=trigram_lookup.get(candidate.pk),
        )
        if row["score"] >= 35 or "Same external registration" in row["reasons"]:
            results.append(row)

    results.sort(key=lambda item: (-item["score"], item["candidate"].name.lower()))
    return results[:limit]


def duplicate_candidates(limit=30):
    """Return high-signal duplicate pairs from bounded same-name buckets."""
    # Very common names (for example Ares/Zeus) create thousands of low-value
    # pair combinations and used to make the moderation queue load tens of
    # thousands of rows. Restrict automatic suggestions to small buckets;
    # moderators can still search any dog explicitly with duplicate_matches().
    bucket_limit = max(limit * 2, 60)
    duplicate_names = list(
        Dog.objects.exclude(normalized_name="")
        .values("normalized_name")
        .annotate(total=Count("pk"))
        .filter(total__gt=1, total__lte=8)
        .order_by("-total", "normalized_name")
        .values_list("normalized_name", flat=True)[:bucket_limit]
    )
    if not duplicate_names:
        return []

    dogs = list(
        Dog.objects.filter(normalized_name__in=duplicate_names)
        .select_related("sire", "dam", "kennel")
        .prefetch_related("registrations")
        .order_by("normalized_name", "name")
    )
    buckets = defaultdict(list)
    for dog in dogs:
        buckets[dog.normalized_name].append(dog)

    rows = []
    for bucket in buckets.values():
        for index, left in enumerate(bucket):
            for right in bucket[index + 1 :]:
                row = _score_duplicate_pair(left, right)
                if row["score"] >= 60:
                    rows.append(row)

    rows.sort(key=lambda item: (-item["score"], item["reference"].name.lower()))
    return rows[:limit]


def moderation_dog_search(query, limit=12):
    """Search dog records for moderator duplicate review without loading the full database."""
    query = (query or "").strip()
    if not query:
        return []

    base = (
        Dog.objects.select_related("kennel", "sire", "dam")
        .prefetch_related("registrations", "aliases")
    )

    if connection.vendor == "postgresql":
        rows = list(
            base.annotate(name_similarity=TrigramSimilarity("name", query))
            .filter(
                Q(name_similarity__gte=0.16)
                | Q(name__icontains=query)
                | Q(aliases__name__icontains=query)
                | Q(registrations__number__icontains=query)
            )
            .distinct()
            .order_by("-name_similarity", "name")[:limit]
        )
        return rows

    direct = list(
        base.filter(
            Q(name__icontains=query)
            | Q(aliases__name__icontains=query)
            | Q(registrations__number__icontains=query)
        )
        .distinct()
        .order_by("name")[:limit]
    )
    if direct:
        return direct

    normalized_query = _normalized_name(query)
    scored = []
    for dog in base.order_by("name")[:1000]:
        ratio = SequenceMatcher(
            None, normalized_query, _normalized_name(dog.name)
        ).ratio()
        if ratio >= 0.45:
            scored.append((ratio, dog))
    scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return [dog for _, dog in scored[:limit]]
