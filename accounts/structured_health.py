"""A compact, evidence-backed staff editor for common canine test findings.

Each field represents a separate result. Never reinterpret historical mixed
text as verified markers; a reviewer selects the actual accepted source.
Breed composition may be recorded privately by staff but not published
without the kennel owner's existing consent workflow.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from registry.dna import parse_breed_composition, percentage_text
from registry.genetic_health import SCREENING_MARKERS
from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, ModerationAudit,
    Submission, VerificationEvent, VerificationState,
)
from registry.permissions import can_review_submissions
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit


_MARKER_CHOICES = [
    ("", "Leave unchanged"),
    ("Clear", "Clear"),
    ("Carrier", "Carrier"),
    ("Affected", "Affected"),
    ("Inconclusive", "Inconclusive"),
    ("Not tested", "Not tested"),
]
_GRADE_CHOICES = [("", "Leave unchanged")] + [
    (f"HD-{grade}", f"HD-{grade}") for grade in "ABCDE"
]
_ELBOW_CHOICES = [("", "Leave unchanged")] + [
    (f"ED-{grade}", f"ED-{grade}") for grade in "0123"
]


class StructuredHealthForm(forms.Form):
    """One edit panel with separate rows for every common screening value."""
    source_submission = forms.ModelChoiceField(
        queryset=Submission.objects.none(), required=False,
        label="Approved health submission", empty_label="Select approved health submission…",
    )
    source_document = forms.ModelChoiceField(
        queryset=DogDocument.objects.none(), required=False,
        label="Or accepted laboratory certificate", empty_label="Select accepted certificate…",
    )
    cmr1 = forms.ChoiceField(required=False, choices=_MARKER_CHOICES, label="CMR1")
    dsra = forms.ChoiceField(required=False, choices=_MARKER_CHOICES, label="DSRA")
    ncl1 = forms.ChoiceField(required=False, choices=_MARKER_CHOICES, label="NCL1")
    hip = forms.ChoiceField(required=False, choices=_GRADE_CHOICES, label="Hip screening (HD)")
    elbow = forms.ChoiceField(required=False, choices=_ELBOW_CHOICES, label="Elbow screening (ED)")
    cane_corso_percentage = forms.DecimalField(
        required=False, min_value=0, max_value=100,
        max_digits=5, decimal_places=2, label="Cane Corso percentage",
        widget=forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01", "placeholder": "e.g. 100"}),
    )
    laboratory = forms.CharField(required=False, max_length=100, label="DNA testing laboratory")
    other_breeds = forms.CharField(
        required=False, max_length=2000, label="Other breeds (if percentage is below 100)",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Boxer: 7.5"}),
        help_text="One breed and its percentage per line; all breeds must total 100%.",
    )
    tested_on = forms.DateField(
        required=False, label="Date shown on certificate",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reviewed = forms.BooleanField(
        label="I checked every changed value against this dog's accepted original laboratory evidence.",
    )

    def __init__(self, *args, dog, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_submission"].queryset = (
            Submission.objects.filter(
                dog=dog, kind=Submission.Kind.HEALTH, status=Submission.Status.APPROVED,
            ).exclude(attachment="").order_by("-created_at")
        )
        self.fields["source_document"].queryset = (
            DogDocument.objects.filter(
                Q(staff_review_only=True,
                  staff_health_record__verification_state=VerificationState.HEALTH_VERIFIED)
                | Q(breed_dna_report__health_record__verification_state=VerificationState.HEALTH_VERIFIED)
                | Q(source_submission__kind=Submission.Kind.DOCUMENT,
                    source_submission__status=Submission.Status.APPROVED),
                dog=dog,
                document_type__in=(DogDocument.DocumentType.HEALTH, DogDocument.DocumentType.DNA),
            ).exclude(file="").distinct().order_by("-created_at")
        )

    def clean(self):
        data = super().clean()
        if bool(data.get("source_submission")) == bool(data.get("source_document")):
            self.add_error(None, "Choose exactly one approved laboratory report.")
        changed = any(data.get(name) for name in ("cmr1", "dsra", "ncl1", "hip", "elbow"))
        pct = data.get("cane_corso_percentage")
        if pct is not None:
            changed = True
            if not (data.get("laboratory") or "").strip():
                self.add_error("laboratory", "Enter the laboratory printed on the breed-composition report.")
            source = data.get("source_document")
            submission = data.get("source_submission")
            # A clinical health certificate must never become a breed-DNA proof.
            if source is not None and source.document_type != DogDocument.DocumentType.DNA:
                self.add_error("source_document", "Choose an accepted DNA certificate for breed composition.")
            if submission is not None and (submission.payload or {}).get("evidence_type") != "breed":
                self.add_error("source_submission", "Choose an approved breed-composition submission.")
            try:
                data["composition"] = parse_breed_composition(
                    pct, data.get("other_breeds") or "",
                )
            except ValidationError as exc:
                self.add_error("other_breeds", exc)
        elif data.get("laboratory") or data.get("other_breeds"):
            self.add_error("cane_corso_percentage", "Enter the reported breed percentage first.")
        if not changed:
            self.add_error(None, "Select at least one test value to change.")
        if data.get("tested_on") and data["tested_on"] > timezone.localdate():
            self.add_error("tested_on", "The report date cannot be in the future.")
        return data


def structured_rows(records):
    """Prepare compact read-only current values without trusting mixed legacy prose."""
    latest = {}
    for record in records:
        if record.verification_state != VerificationState.HEALTH_VERIFIED:
            continue
        code = record.test_type.strip().upper()
        if code not in {"CMR1", "DSRA", "NCL1", "HD", "ED"}:
            continue
        if code not in latest or (
            (record.tested_on or timezone.datetime.min.date()), record.created_at, record.pk
        ) > (
            (latest[code].tested_on or timezone.datetime.min.date()), latest[code].created_at, latest[code].pk
        ):
            latest[code] = record
    return latest


@login_required
@require_POST
def save_structured_health(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog.objects.select_related("kennel"), pk=pk)
    form = StructuredHealthForm(request.POST, dog=dog)
    if not form.is_valid():
        messages.error(
            request,
            "Nothing was saved. Check the evidence and the highlighted fields: " + form.errors.as_text(),
        )
        return redirect("accounts:reviewed-dog-health", pk=pk)
    data = form.cleaned_data
    fields = (
        ("CMR1", "cmr1"), ("DSRA", "dsra"), ("NCL1", "ncl1"),
        ("HD", "hip"), ("ED", "elbow"),
    )
    with transaction.atomic():
        submission = data.get("source_submission")
        document = data.get("source_document")
        if submission:
            submission = get_object_or_404(
                Submission.objects.select_for_update(),
                pk=submission.pk, dog=dog, kind=Submission.Kind.HEALTH,
                status=Submission.Status.APPROVED,
            )
            document = DogDocument.objects.filter(
                dog=dog, source_submission=submission,
            ).first()
        else:
            document = get_object_or_404(
                DogDocument.objects.select_for_update(), pk=document.pk, dog=dog,
            )
        if document and document.is_public:
            document.is_public = False
            document.save(update_fields=["is_public"])
        source_key = f"submission:{submission.pk}" if submission else f"document:{document.pk}"
        when = data.get("tested_on")
        existing = structured_rows(
            list(HealthRecord.objects.select_for_update().filter(dog=dog).order_by("-created_at"))
        )
        updates = 0
        for code, field in fields:
            result = data.get(field)
            if not result:
                continue
            previous = existing.get(code)
            if (
                previous and previous.result.strip().lower() == result.lower()
                and (not when or previous.tested_on == when)
            ):
                continue
            # Preserve the original approved row and its immutable evidence.
            # Carry forward the previous privacy choice BEFORE marking the old
            # row superseded; otherwise the replacement would be hidden too.
            new_visibility = previous.is_public if previous else True
            if previous and previous.is_public:
                previous.is_public = False
                previous.save(update_fields=["is_public"])
            direct_document = (
                document if document and not HealthRecord.objects.filter(
                    evidence_document=document
                ).exists() else None
            )
            record = HealthRecord.objects.create(
                dog=dog, test_type=code, result=result, tested_on=when,
                verification_state=VerificationState.HEALTH_VERIFIED,
                is_public=new_visibility,
                evidence_document=direct_document,
                notes=f"Structured staff health transcription from accepted {source_key}",
            )
            VerificationEvent.objects.create(
                dog=dog, health_record=record, state=VerificationState.HEALTH_VERIFIED,
                reviewer=request.user,
                note=f"Reviewer independently checked structured {code} result against {source_key}.",
            )
            record_audit(
                action=ModerationAudit.Action.VERIFICATION,
                actor=request.user, dog=dog,
                summary={
                    "kind": "structured_health_result", "health_record_id": record.pk,
                    "test_type": code, "result": result,
                    "superseded_health_record_id": previous.pk if previous else None,
                    "source": source_key,
                },
                note="Staff saved evidence-backed individual test result; original document stays private.",
            )
            existing[code] = record
            updates += 1

        pct = data.get("cane_corso_percentage")
        if pct is not None:
            # Publication permission is NEVER inferred from staff review. If
            # there is an owner-consented report for this source, editing its
            # values retains its existing consent; a new source is private.
            if document is None or document.document_type != DogDocument.DocumentType.DNA:
                form.add_error("source_document", "A stored accepted DNA report is required.")
            else:
                prior = BreedDNAReport.objects.select_for_update().filter(
                    health_record__dog=dog, evidence_document=document,
                ).select_related("health_record").first()
                if prior:
                    rec = prior.health_record
                    old = {
                        "percentage": str(prior.cane_corso_percentage),
                        "provider": prior.provider,
                    }
                    prior.cane_corso_percentage = pct
                    prior.composition = data["composition"]
                    prior.provider = data["laboratory"].strip()
                    prior.save(update_fields=["cane_corso_percentage", "composition", "provider"])
                    rec.result = percentage_text(pct) + "% Cane Corso"
                    rec.tested_on = when or rec.tested_on
                    rec.save(update_fields=["result", "tested_on"])
                else:
                    old = None
                    rec = HealthRecord.objects.create(
                        dog=dog, test_type="DNA breed composition",
                        result=percentage_text(pct) + "% Cane Corso",
                        tested_on=when, verification_state=VerificationState.HEALTH_VERIFIED,
                        is_public=False,
                        notes=f"Structured staff DNA transcription from accepted {source_key}; awaiting owner consent",
                    )
                    BreedDNAReport.objects.create(
                        health_record=rec, evidence_document=document,
                        provider=data["laboratory"].strip(),
                        cane_corso_percentage=pct, composition=data["composition"],
                        consent_public_summary=False, consent_full_report=False,
                    )
                VerificationEvent.objects.create(
                    dog=dog, health_record=rec, state=VerificationState.HEALTH_VERIFIED,
                    reviewer=request.user,
                    note=f"Staff reviewed breed composition against {source_key}; consent unchanged.",
                )
                record_audit(
                    action=ModerationAudit.Action.VERIFICATION,
                    actor=request.user, dog=dog,
                    summary={
                        "kind": "structured_breed_composition", "health_record_id": rec.pk,
                        "percentage": percentage_text(pct), "source": source_key, "before": old,
                        "public": rec.is_public,
                    },
                    note="Evidence-backed breed composition recorded. Existing owner consent unchanged.",
                )
                updates += 1

        if form.errors:
            messages.error(request, "The DNA source is not an approved stored breed report.")
            transaction.set_rollback(True)
            return redirect("accounts:reviewed-dog-health", pk=pk)
        if updates:
            invalidate_public_content()
    if not updates:
        messages.info(request, "No values changed. The previously verified results were retained.")
    else:
        messages.success(
            request, f"Saved {updates} reviewed result{'s' if updates != 1 else ''}."
            + (" Breed-DNA publication remains subject to owner consent." if pct is not None else "")
        )
    return redirect("accounts:reviewed-dog-health", pk=pk)
