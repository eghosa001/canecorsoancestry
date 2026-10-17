"""Human review of submitted laboratory images and typed public summaries."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from registry.dna import parse_breed_composition, percentage_text
from registry.genetic_health import SCREENING_MARKERS
from registry.models import (
    BreedDNAReport, Dog, HealthRecord, ModerationAudit, Submission,
)
from registry.permissions import can_review_submissions
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit
from registry.verification import verify_submission


class HealthTranscriptionForm(forms.Form):
    publish_primary = forms.BooleanField(
        required=False, initial=True,
        label="Show the main reviewed result on the public dog profile",
    )
    laboratory = forms.CharField(required=False, max_length=100, label="Laboratory named in the image")
    breed_percentage = forms.DecimalField(
        required=False, max_digits=5, decimal_places=2, min_value=0, max_value=100,
        label="Cane Corso percentage from the report",
    )
    other_breeds = forms.CharField(
        required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}),
        label="Other breed percentages", help_text="Breed: percentage on each line; total must equal 100.",
    )
    reviewed = forms.BooleanField(
        label="I personally checked these entries against this dog's original certificate.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for code, label in SCREENING_MARKERS:
            self.fields["status_" + code] = forms.ChoiceField(
                required=False,
                choices=(("", "No verified result in this image"), ("Clear", "Clear"),
                         ("Carrier", "Carrier"), ("Affected", "Affected")),
                label=code + " — " + label,
            )
            self.fields["publish_" + code] = forms.BooleanField(
                required=False, label="Display approved " + code + " result publicly",
            )

    def clean(self):
        data = super().clean()
        for code, _ in SCREENING_MARKERS:
            if data.get("publish_" + code) and not data.get("status_" + code):
                self.add_error("status_" + code, "Select the actual lab result before publishing.")
        return data


def health_transcription_initial(submission):
    p = submission.payload or {}
    initial = {
        "publish_primary": p.get("publish_primary", True),
        "laboratory": p.get("dna_provider") or "",
        "breed_percentage": p.get("cane_corso_percentage") or None,
        "other_breeds": p.get("other_breeds") or "",
    }
    for code, _ in SCREENING_MARKERS:
        entry = (p.get("reviewed_markers") or {}).get(code, {})
        initial["status_" + code] = entry.get("status", "")
        initial["publish_" + code] = entry.get("publish", False)
    return initial


@login_required
@require_POST
def transcribe_health_submission(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    form = HealthTranscriptionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Check the laboratory-result form and select a status for every enabled item.")
        return redirect("accounts:moderation-submission", pk=pk)
    with transaction.atomic():
        submission = get_object_or_404(
            Submission.objects.select_for_update(),
            pk=pk, kind=Submission.Kind.HEALTH, status=Submission.Status.PENDING,
        )
        if not submission.dog_id or not submission.attachment:
            raise PermissionDenied("Private report and existing dog are required.")
        payload = dict(submission.payload or {})
        data = form.cleaned_data
        if payload.get("evidence_type") == "breed":
            provider = (data.get("laboratory") or "").strip()
            pct = data.get("breed_percentage")
            if not provider or pct is None:
                messages.error(request, "The reviewed breed report needs its laboratory and exact percentage.")
                return redirect("accounts:moderation-submission", pk=pk)
            try:
                composition = parse_breed_composition(pct, data.get("other_breeds") or "")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("accounts:moderation-submission", pk=pk)
            if not payload.get("acknowledge_public_summary"):
                raise PermissionDenied("Staff cannot create owner DNA publication consent.")
            payload.update({
                "dna_provider": provider,
                "cane_corso_percentage": str(pct),
                "other_breeds": data.get("other_breeds") or "",
                "result": percentage_text(pct) + "% Cane Corso",
                "allow_full_report_publication": False,
            })
        markers = {}
        for code, _ in SCREENING_MARKERS:
            status = data.get("status_" + code) or ""
            if status:
                markers[code] = {
                    "status": status,
                    "publish": bool(data.get("publish_" + code)),
                }
        payload["reviewed_markers"] = markers
        primary_code = (payload.get("test_type") or "").strip().upper()
        if primary_code in markers:
            payload["result"] = markers[primary_code]["status"]
            payload["publish_primary"] = markers[primary_code]["publish"]
        else:
            payload["publish_primary"] = bool(data.get("publish_primary"))
        submission.payload = payload
        submission.save(update_fields=["payload", "updated_at"])
        record_audit(
            action=ModerationAudit.Action.VERIFICATION,
            actor=request.user, dog=submission.dog, submission=submission,
            summary={
                "kind": "lab_report_transcription", "markers": markers,
                "primary_public": payload["publish_primary"],
                "breed_summary": payload.get("cane_corso_percentage") if payload.get("evidence_type") == "breed" else None,
            },
            note="Reviewer transcribed structured results from original private laboratory evidence.",
        )
        verify_submission(submission)
    messages.success(request, "Laboratory results saved for review. Approve the submission separately to publish enabled summaries.")
    return redirect("accounts:moderation-submission", pk=pk)


@login_required
def reviewed_dog_health(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog.objects.select_related("kennel"), pk=pk)
    records = list(
        HealthRecord.objects.filter(dog=dog)
        .select_related("breed_dna_report", "evidence_document", "breed_dna_report__evidence_document")
        .order_by("-created_at")[:150]
    )
    pending = list(Submission.objects.filter(
        dog=dog, kind=Submission.Kind.HEALTH, status=Submission.Status.PENDING
    ).order_by("-created_at")[:30])
    return render(request, "accounts/moderator_health_results.html", {
        "dog": dog, "records": records, "pending": pending,
    })


@login_required
@require_POST
def toggle_health_result(request, pk, record_id):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.POST.get("visibility") not in ("show", "hide"):
        return HttpResponseBadRequest("Choose Show or Hide.")
    show = request.POST["visibility"] == "show"
    with transaction.atomic():
        record = get_object_or_404(
            HealthRecord.objects.select_for_update(), pk=record_id, dog_id=pk
        )
        if show and record.verification_state != "health":
            messages.error(request, "Only approved, evidence-reviewed results may be public.")
            return redirect("accounts:reviewed-dog-health", pk=pk)
        if show and BreedDNAReport.objects.filter(
            health_record=record, consent_public_summary=False
        ).exists():
            messages.error(request, "DNA breed percentages require the owner's consent before publication.")
            return redirect("accounts:reviewed-dog-health", pk=pk)
        if record.is_public != show:
            record.is_public = show
            record.save(update_fields=["is_public"])
            record_audit(
                action=ModerationAudit.Action.VERIFICATION,
                actor=request.user, dog=record.dog,
                summary={"kind": "health_summary_visibility", "health_record_id": record.pk, "public": show},
                note="Moderator updated PUBLIC SUMMARY visibility; original health image remains private.",
            )
            invalidate_public_content()
    messages.success(request, "Public health-result visibility updated.")
    return redirect("accounts:reviewed-dog-health", pk=pk)
