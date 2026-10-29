"""Human review of submitted laboratory images and typed public summaries."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from registry.dna import parse_breed_composition, percentage_text
from registry.genetic_health import MARKER_CODES, SCREENING_MARKERS, SCREENING_RESULTS, readable_health_result, unstructured_breed_claim
from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, ModerationAudit, Submission, VerificationState, VerificationEvent,
)
from registry.permissions import can_review_submissions
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit
from registry.verification import verify_submission


class HealthTranscriptionForm(forms.Form):
    publish_primary = forms.BooleanField(
        required=False, initial=True,
        label="Flag the main result for the final public-card review",
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
                         ("Carrier", "Carrier"), ("Affected", "Affected"),
                         ("Inconclusive", "Inconclusive"), ("Not tested", "Not tested")),
                label=code + " — " + label,
            )
            self.fields["publish_" + code] = forms.BooleanField(
                required=False, label="Flag " + code + " for the final public-card review",
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
    messages.success(request, "Laboratory transcription saved. Approved results will appear automatically on the dog's public profile.")
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
        "add_condition_form": AdditionalHealthConditionForm(dog=dog),
    })



def _manual_health_result(form, data):
    """Preserve staff-entered laboratory values without interpreting scores."""
    text_result = (data.get("result") or "").strip()
    number = data.get("numeric_value")
    unit = (data.get("result_unit") or "").strip()
    if text_result and number is not None:
        form.add_error("numeric_value", "Use either the reported result field or the numeric value field, not both.")
    if number is None and not text_result:
        form.add_error("result", "Enter the laboratory result or an exact numerical measurement.")
    if unit and number is None:
        form.add_error("result_unit", "Enter a numeric value before specifying its unit.")
    if number is not None:
        return (format(number, "f") + (" " + unit if unit else "")).strip()
    return text_result


class ReviewedHealthResultForm(forms.Form):
    """Edit the public-facing transcription; never rewrite the private report."""
    test_type = forms.CharField(max_length=100, label="Test or condition on the report")
    result = forms.CharField(max_length=160, required=False, label="Reported result / grade",
        widget=forms.TextInput(attrs={"list": "health-reported-status-options", "autocomplete": "off",
                                      "placeholder": "HD-A, ED-0, Clear or a score such as 12/24"}),
        help_text="Copy grades and multi-part scores exactly as shown in the certificate. Leave blank if using the numeric field.")
    numeric_value = forms.DecimalField(required=False, max_digits=12, decimal_places=4,
        label="Exact numeric measurement (optional)",
        help_text="Enter a number such as 12.5 or 0. Do not round or infer a value; clear Reported result / grade first.")
    result_unit = forms.CharField(required=False, max_length=24,
        label="Measurement unit (optional)", help_text="Only for the numeric field, e.g. mm, ng/mL, %.")
    tested_on = forms.DateField(
        required=False, label="Test date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    laboratory = forms.CharField(required=False, max_length=100, label="Testing laboratory")
    breed_percentage = forms.DecimalField(
        required=False, max_digits=5, decimal_places=2,
        min_value=0, max_value=100, label="Cane Corso percentage",
    )
    other_breeds = forms.CharField(
        required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Other breeds and percentages",
        help_text="One breed per line, e.g. Boxer: 12.5. All percentages must total 100.",
    )
    reviewed = forms.BooleanField(
        label="I checked the edited public summary against the original laboratory evidence.",
    )

    def __init__(self, *args, record, **kwargs):
        self.breed_report = getattr(record, "breed_dna_report", None)
        initial = {
            "test_type": record.test_type,
            "result": record.result,
            "tested_on": record.tested_on,
        }
        if self.breed_report:
            initial.update({
                "laboratory": self.breed_report.provider,
                "breed_percentage": self.breed_report.cane_corso_percentage,
                "other_breeds": "\n".join(
                    f'{entry["breed"]}: {entry["percentage"]}'
                    for entry in self.breed_report.composition
                    if entry.get("breed", "").lower() != "cane corso"
                ),
            })
        kwargs.setdefault("initial", initial)
        super().__init__(*args, **kwargs)
        if self.breed_report:
            # Breed claims have dedicated validated structured data.
            self.fields["test_type"].disabled = True
            self.fields["result"].disabled = True
        else:
            for name in ("laboratory", "breed_percentage", "other_breeds"):
                self.fields.pop(name)

    def clean(self):
        data = super().clean()
        if data.get("tested_on") and data["tested_on"] > timezone.localdate():
            self.add_error("tested_on", "A test date cannot be in the future.")
        if self.breed_report:
            if not (data.get("laboratory") or "").strip():
                self.add_error("laboratory", "Name the laboratory shown on the report.")
            if data.get("breed_percentage") is None:
                self.add_error("breed_percentage", "Enter the exact reported percentage.")
            else:
                try:
                    data["composition"] = parse_breed_composition(
                        data["breed_percentage"], data.get("other_breeds") or "",
                    )
                except ValidationError as exc:
                    self.add_error("other_breeds", exc)
        else:
            code = (data.get("test_type") or "").strip().upper()
            result = _manual_health_result(self, data)
            data["resolved_result"] = result
            if code in MARKER_CODES and result.lower() not in SCREENING_RESULTS:
                self.add_error("result", "Choose Clear, Carrier, Affected, Inconclusive or Not tested as stated in the report.")
            if unstructured_breed_claim(code):
                self.add_error("test_type", "Breed composition must use the dedicated owner-consented DNA report.")
        return data



class AdditionalHealthConditionForm(forms.Form):
    """Transcribe a condition missed by the initial extraction from an approved report."""
    source_submission = forms.ModelChoiceField(
        queryset=Submission.objects.none(), required=False,
        label="Approved member report", empty_label="Choose approved report…",
    )
    source_document = forms.ModelChoiceField(
        queryset=DogDocument.objects.none(), required=False,
        label="Or approved Health/DNA document", empty_label="Choose accepted certificate…" ,
    )
    test_type = forms.CharField(max_length=100, label="Exact genetic condition / test name")
    result = forms.CharField(max_length=160, required=False, label="Result / grade exactly as reported",
        widget=forms.TextInput(attrs={"list": "health-reported-status-options", "autocomplete": "off",
                                      "placeholder": "HD-A, ED-0, 12/24 or Clear"}),
        help_text="Enter a grade, status or multi-part score exactly; leave blank when using the numeric field.")
    numeric_value = forms.DecimalField(required=False, max_digits=12, decimal_places=4,
        label="Exact numeric value (optional)",
        help_text="Enter 0, 12.5, etc. without rounding; use the unit field if needed.")
    result_unit = forms.CharField(required=False, max_length=24,
        label="Measurement unit (optional)")
    tested_on = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Test date",
    )
    reviewed = forms.BooleanField(
        label="I have checked this additional condition and its result in the approved report.",
    )

    def __init__(self, *args, dog, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_submission"].queryset = Submission.objects.filter(
            dog=dog, kind=Submission.Kind.HEALTH, status=Submission.Status.APPROVED
        ).exclude(attachment="").order_by("-created_at")
        self.fields["source_document"].queryset = DogDocument.objects.filter(
            Q(staff_review_only=True,
              staff_health_record__verification_state=VerificationState.HEALTH_VERIFIED)
            | Q(source_submission__kind=Submission.Kind.DOCUMENT,
                source_submission__status=Submission.Status.APPROVED),
            dog=dog, document_type__in=(DogDocument.DocumentType.HEALTH, DogDocument.DocumentType.DNA),
        ).exclude(file="").distinct().order_by("-created_at")

    def clean(self):
        data = super().clean()
        test_type = (data.get("test_type") or "").strip()
        result = _manual_health_result(self, data)
        data["resolved_result"] = result
        if bool(data.get("source_submission")) == bool(data.get("source_document")):
            self.add_error(None, "Choose exactly one approved source report.")
        if unstructured_breed_claim(test_type):
            self.add_error("test_type", "Breed percentages require a separately verified, owner-consented DNA record.")
        if test_type.upper() in MARKER_CODES and result.lower() not in SCREENING_RESULTS:
            self.add_error("result", "Use Clear, Carrier or Affected for a featured genetic marker.")
        if data.get("tested_on") and data["tested_on"] > timezone.localdate():
            self.add_error("tested_on", "The test date cannot be in the future.")
        return data


@login_required
@require_POST
def add_reviewed_health_condition(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog, pk=pk)
    form = AdditionalHealthConditionForm(request.POST, dog=dog)
    if not form.is_valid():
        messages.error(request, "Check the additional condition and select its approved source document: " + form.errors.as_text())
        return redirect("accounts:reviewed-dog-health", pk=pk)
    data = form.cleaned_data
    with transaction.atomic():
        source = None
        document = None
        if data.get("source_submission"):
            # Approved member source, always belonging to this dog.
            source = get_object_or_404(
                Submission.objects.select_for_update(),
                pk=data["source_submission"].pk, dog=dog, kind=Submission.Kind.HEALTH,
                status=Submission.Status.APPROVED,
            )
            source_marker = "Moderator condition transcribed from approved submission " + str(source.pk)
            source_category = str((source.payload or {}).get("evidence_type") or "health")
            source_id = str(source.pk)
        else:
            # An approved Health/DNA document or Super Admin archival laboratory report.
            document = get_object_or_404(
                DogDocument.objects.select_for_update(of=("self",)).filter(
                    Q(staff_review_only=True,
                      staff_health_record__verification_state=VerificationState.HEALTH_VERIFIED)
                    | Q(source_submission__kind=Submission.Kind.DOCUMENT,
                        source_submission__status=Submission.Status.APPROVED),
                ),
                pk=data["source_document"].pk, dog=dog,
                document_type__in=(DogDocument.DocumentType.HEALTH, DogDocument.DocumentType.DNA),
            )
            source_marker = "Moderator condition transcribed from approved document " + str(document.pk)
            source_category = document.document_type
            source_id = str(document.pk)
        source_note = source_marker + "; evidence_category=" + source_category
        if HealthRecord.objects.filter(
            dog=dog, test_type__iexact=data["test_type"].strip(),
            tested_on=data.get("tested_on"), notes__in=(source_note, source_marker),
        ).exists():
            messages.error(request, "This condition and date have already been transcribed from that document.")
            return redirect("accounts:reviewed-dog-health", pk=pk)
        supporting_document = document or DogDocument.objects.filter(
            dog=dog, source_submission=source,
        ).first()
        # A document used as laboratory evidence is confidential even if it
        # was initially uploaded as a general document with public visibility.
        if supporting_document and supporting_document.is_public:
            supporting_document.is_public = False
            supporting_document.save(update_fields=["is_public"])
        direct_evidence = (
            supporting_document
            if supporting_document and not HealthRecord.objects.filter(
                evidence_document=supporting_document,
            ).exists() else None
        )
        record = HealthRecord.objects.create(
            dog=dog, test_type=data["test_type"].strip(),
            result=readable_health_result(data["resolved_result"]),
            tested_on=data.get("tested_on"), verification_state=VerificationState.HEALTH_VERIFIED,
            is_public=True, notes=source_note, evidence_document=direct_evidence,
        )
        VerificationEvent.objects.create(
            dog=dog, health_record=record, state=VerificationState.HEALTH_VERIFIED,
            reviewer=request.user,
            note="Additional condition manually checked against approved private laboratory report " + source_id,
        )
        record_audit(
            action=ModerationAudit.Action.VERIFICATION, actor=request.user,
            dog=dog, submission=source,
            summary={
                "kind": "additional_health_condition",
                "health_record_id": record.pk,
                "source_submission_id": str(source.pk) if source else None,
                "source_document_id": document.pk if document else None,
                "test_type": record.test_type, "result": record.result,
                "public": True,
            },
            note="Staff reviewer added a laboratory condition; original evidence remains private.",
        )
    invalidate_public_content()
    messages.success(request, "Additional reviewed condition saved and shown on the dog's public profile.")
    return redirect("accounts:edit-reviewed-health-result", pk=pk, record_id=record.pk)


@login_required
@never_cache
def edit_reviewed_health_result(request, pk, record_id):
    """Post-approval final editorial step, with an explicit publication choice."""
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.method not in ("GET", "POST"):
        return HttpResponseBadRequest("Use the review form.")
    record = get_object_or_404(
        HealthRecord.objects.select_related(
            "dog", "breed_dna_report", "breed_dna_report__evidence_document",
            "evidence_document",
        ),
        pk=record_id, dog_id=pk,
    )
    if record.verification_state != VerificationState.HEALTH_VERIFIED:
        raise PermissionDenied("An approved evidence-reviewed result is required.")
    if request.method == "POST":
        intent = request.POST.get("intent")
        if intent not in ("save", "publish"):
            return HttpResponseBadRequest("Choose Save privately or Publish.")
        with transaction.atomic():
            record = get_object_or_404(
                HealthRecord.objects.select_for_update(of=("self",)).select_related("breed_dna_report"),
                pk=record_id, dog_id=pk, verification_state=VerificationState.HEALTH_VERIFIED,
            )
            form = ReviewedHealthResultForm(request.POST, record=record)
            if form.is_valid():
                data = form.cleaned_data
                report = getattr(record, "breed_dna_report", None)
                if intent == "publish" and report and not report.consent_public_summary:
                    form.add_error(None, "The owner has not authorized publication of this DNA breed summary.")
                else:
                    before = {
                        "test_type": record.test_type, "result": record.result,
                        "tested_on": record.tested_on.isoformat() if record.tested_on else None,
                        "public": record.is_public,
                    }
                    record.tested_on = data.get("tested_on")
                    if report:
                        report.provider = data["laboratory"].strip()
                        report.cane_corso_percentage = data["breed_percentage"]
                        report.composition = data["composition"]
                        report.save(update_fields=["provider", "cane_corso_percentage", "composition"])
                        record.test_type = "DNA breed composition"
                        record.result = percentage_text(data["breed_percentage"]) + "% Cane Corso"
                    else:
                        record.test_type = data["test_type"].strip()
                        record.result = readable_health_result(data["resolved_result"])
                    record.is_public = intent == "publish"
                    record.save(update_fields=["test_type", "result", "tested_on", "is_public"])
                    record_audit(
                        action=ModerationAudit.Action.VERIFICATION,
                        actor=request.user, dog=record.dog,
                        summary={
                            "kind": "moderator_post_approval_health_editor",
                            "health_record_id": record.pk,
                            "before": before,
                            "after": {
                                "test_type": record.test_type, "result": record.result,
                                "tested_on": record.tested_on.isoformat() if record.tested_on else None,
                                "public": record.is_public,
                                "provider": report.provider if report else None,
                                "composition": report.composition if report else None,
                            },
                        },
                        note="Moderator confirmed edited public summary against original private evidence.",
                    )
                    invalidate_public_content()
                    messages.success(
                        request,
                        "Reviewed summary published on the dog's profile."
                        if record.is_public else
                        "Reviewed summary saved privately. Publish it when the public card is ready.",
                    )
                    return redirect("accounts:reviewed-dog-health", pk=pk)
    else:
        form = ReviewedHealthResultForm(record=record)
    report = getattr(record, "breed_dna_report", None)
    source_document = record.evidence_document or (report.evidence_document if report else None)
    if not source_document:
        # A source can back several conditions, while the model's direct
        # evidence link is one-to-one. Recover the approved source via audit.
        provenance = ModerationAudit.objects.filter(
            dog=record.dog, action=ModerationAudit.Action.VERIFICATION,
            summary__kind="additional_health_condition",
            summary__health_record_id=record.pk,
        ).order_by("-pk").first()
        if provenance:
            details = provenance.summary or {}
            if details.get("source_document_id"):
                source_document = DogDocument.objects.filter(
                    dog=record.dog, pk=details["source_document_id"],
                ).first()
            elif details.get("source_submission_id"):
                source_document = DogDocument.objects.filter(
                    dog=record.dog,
                    source_submission_id=details["source_submission_id"],
                ).first()
    return render(request, "accounts/moderator_health_edit.html", {
        "dog": record.dog, "record": record, "form": form,
        "breed_report": report, "source_document": source_document,
        "can_publish": not report or report.consent_public_summary,
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
