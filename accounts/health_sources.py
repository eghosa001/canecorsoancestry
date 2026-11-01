"""Approved canine laboratory evidence available to authorized staff reviewers.

The same queries supply the staff selector, document previews and permission
checks. Evidence must belong to the exact dog and have an approved source, or
be independently verified staff archival evidence. No PDF/image contents are
parsed or inferred here.
"""
import re

from django.db.models import Q
from django.urls import reverse

from registry.models import (
    DogDocument, ModerationAudit, Submission, VerificationState,
)

_SUBMISSION_ID_NOTE = re.compile(
    r"Moderator reviewed private lab evidence for submission "
    r"([0-9a-fA-F-]{36})(?:\b|$)"
)


def approved_health_submissions(dog):
    return (
        Submission.objects.filter(
            dog=dog, kind=Submission.Kind.HEALTH,
            status=Submission.Status.APPROVED,
        ).exclude(attachment="").order_by("-created_at")
    )


def accepted_health_documents(dog):
    return (
        DogDocument.objects.filter(
            Q(
                staff_review_only=True,
                staff_health_record__verification_state=VerificationState.HEALTH_VERIFIED,
            )
            | Q(
                breed_dna_report__health_record__verification_state=VerificationState.HEALTH_VERIFIED,
            )
            | Q(
                source_submission__kind=Submission.Kind.DOCUMENT,
                source_submission__status=Submission.Status.APPROVED,
            ),
            dog=dog,
            document_type__in=(
                DogDocument.DocumentType.HEALTH,
                DogDocument.DocumentType.DNA,
            ),
        ).exclude(file="").distinct().order_by("-created_at")
    )


def approved_evidence_entries(dog):
    """List only the exact sources the staff correction forms can accept."""
    items = []
    for submission in approved_health_submissions(dog).select_related("submitted_by")[:200]:
        payload = submission.payload or {}
        laboratory = str(
            payload.get("dna_provider") or payload.get("laboratory") or ""
        ).strip()
        items.append({
            "kind": "submission",
            "source_id": str(submission.pk),
            "label": str(payload.get("test_type") or "Health/DNA laboratory upload"),
            "filename": submission.attachment.name.rsplit("/", 1)[-1],
            "laboratory": laboratory,
            "date": submission.created_at,
            "preview_url": reverse(
                "accounts:preview-health-submission",
                args=[dog.pk, submission.pk],
            ),
        })
    for document in accepted_health_documents(dog).select_related("source_submission")[:200]:
        payload = (
            document.source_submission.payload
            if document.source_submission_id else {}
        ) or {}
        laboratory = str(
            payload.get("dna_provider") or payload.get("laboratory") or ""
        ).strip()
        items.append({
            "kind": "document",
            "source_id": str(document.pk),
            "label": document.title,
            "filename": document.file.name.rsplit("/", 1)[-1],
            "laboratory": laboratory,
            "date": document.created_at,
            "preview_url": reverse(
                "accounts:preview-health-document",
                args=[dog.pk, document.pk],
            ),
        })
    return items


def source_for_record(record, evidence_entries):
    """Resolve exact provenance only; never attach an unrelated dog's upload."""
    doc = record.evidence_document
    report = getattr(record, "breed_dna_report", None)
    if doc is None and report is not None:
        doc = report.evidence_document
    if doc is not None:
        if doc.source_submission_id:
            for item in evidence_entries:
                if (item["kind"] == "submission"
                        and item["source_id"] == str(doc.source_submission_id)):
                    return item
        for item in evidence_entries:
            if item["kind"] == "document" and item["source_id"] == str(doc.pk):
                return item

    provenance = ModerationAudit.objects.filter(
        dog_id=record.dog_id,
        summary__kind="additional_health_condition",
        summary__health_record_id=record.pk,
    ).order_by("-pk").values_list("summary", flat=True).first()
    if provenance:
        for key, kind in (
            ("source_submission_id", "submission"),
            ("source_document_id", "document"),
        ):
            source_id = provenance.get(key)
            if source_id is not None:
                for item in evidence_entries:
                    if item["kind"] == kind and item["source_id"] == str(source_id):
                        return item

    note = _SUBMISSION_ID_NOTE.search(record.notes or "")
    if note:
        for item in evidence_entries:
            if (item["kind"] == "submission"
                    and item["source_id"] == note.group(1)):
                return item

    # Structured corrections may share a single certificate. Because
    # evidence_document is OneToOne, their durable source key is in notes
    # and the audit entry rather than on every HealthRecord.
    matched_key = re.search(
        r"(?:Structured staff health transcription from accepted |"
        r"Structured staff DNA transcription from accepted )"
        r"(submission|document):([0-9a-fA-F-]+)",
        record.notes or "",
    )
    if matched_key:
        for item in evidence_entries:
            if (
                item["kind"] == matched_key.group(1)
                and item["source_id"] == matched_key.group(2)
            ):
                return item
    return None
