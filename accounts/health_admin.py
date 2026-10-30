"""Super Admin-only historical health and DNA evidence management.

Evidence review is not owner permission. Staff-uploaded reports are private;
breed-composition summaries require independently recorded owner consent.
"""
import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from registry.dna import parse_breed_composition, percentage_text
from registry.genetic_health import MARKER_CODES, SCREENING_RESULTS, readable_health_result, unstructured_breed_claim
from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, ModerationAudit,
    VerificationEvent, VerificationState,
)
from registry.permissions import can_manage_verification
from registry.public_freshness import invalidate_public_content
from registry.health_publication import publication_status
from registry.services import record_audit

from .forms import validate_document_upload, DOCUMENT_ACCEPT


class HistoricalHealthEvidenceForm(forms.Form):
    RECORD_TYPES = (
        ("health", "Health screening (hips, elbows, heart, etc.)"),
        ("dna", "Genetic marker / DNA parentage"),
        ("breed", "DNA breed composition (private until owner consent)"),
    )
    record_type = forms.ChoiceField(choices=RECORD_TYPES, label="Record category")
    test_type = forms.CharField(max_length=100, required=False, label="Test / genetic marker")
    result = forms.CharField(max_length=160, required=False, label="Result as stated by laboratory",
        widget=forms.TextInput(attrs={"list": "health-reported-status-options", "autocomplete": "off"}))
    tested_on = forms.DateField(
        required=False, label="Test date", widget=forms.DateInput(attrs={"type": "date"})
    )
    laboratory = forms.CharField(
        max_length=100, required=False, label="Issuing laboratory / testing company"
    )
    cane_corso_percentage = forms.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100,
        required=False, label="Cane Corso percentage from laboratory"
    )
    other_breeds = forms.CharField(
        max_length=2000, required=False, label="Other breeds and percentages",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Boxer: 7.5"}),
        help_text="One breed per line: Breed: percentage. Total must equal exactly 100%.",
    )
    source_reference = forms.CharField(
        max_length=220, label="Evidence source / certificate reference",
        help_text="Identify the laboratory record, report ID or authoritative historical source.",
    )
    source_url = forms.URLField(
        required=False, label="Optional public source URL",
        help_text="Reference only. This does not grant permission to publish the report.",
    )
    attachment = forms.FileField(
        label="Original laboratory certificate / evidence",
        widget=forms.ClearableFileInput(attrs={"accept": DOCUMENT_ACCEPT}),
        validators=[validate_document_upload],
        help_text="Required PDF or readable image, maximum 20 MB. Staff-only; never made public by this form.",
    )
    notes = forms.CharField(
        required=False, max_length=1000, label="Review notes",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    review_attestation = forms.BooleanField(
        label="I checked this evidence against the exact dog and transcribed the result accurately.",
    )

    def clean(self):
        data = super().clean()
        if data.get("tested_on") and data["tested_on"] > timezone.localdate():
            self.add_error("tested_on", "The test date cannot be in the future.")
        if data.get("record_type") == "breed":
            if not (data.get("laboratory") or "").strip():
                self.add_error("laboratory", "Enter the laboratory named on the report.")
            if data.get("cane_corso_percentage") is None:
                self.add_error("cane_corso_percentage", "Copy the laboratory percentage.")
            else:
                try:
                    data["composition"] = parse_breed_composition(
                        data["cane_corso_percentage"], data.get("other_breeds") or ""
                    )
                except ValidationError as exc:
                    self.add_error("other_breeds", exc)
                else:
                    data["test_type"] = "DNA breed composition"
                    data["result"] = (
                        percentage_text(data["cane_corso_percentage"]) + "% Cane Corso"
                    )
        else:
            for field in ("test_type", "result"):
                if not (data.get(field) or "").strip():
                    self.add_error(field, "Required for a health or genetic test.")
            if (data.get("test_type") or "").strip().upper() in MARKER_CODES and (
                (data.get("result") or "").strip().lower() not in SCREENING_RESULTS
            ):
                self.add_error("result", "Use the actual recorded status: Clear, Carrier, Affected, Inconclusive or Not tested.")
            if unstructured_breed_claim(data.get("test_type")):
                self.add_error(
                    "test_type",
                    "Breed DNA/composition cannot be saved as a public health test. "
                    "Choose the dedicated DNA breed composition category; owner "
                    "publication consent is required. Enter actual health markers "
                    "as separate tests.",
                )
        return data


def _require_super_admin(user):
    if not can_manage_verification(user):
        raise PermissionDenied("Only an active Super Admin may manage historical test evidence.")


def _context(request, **extra):
    return {
        "staff_role": "owner",
        "staff_role_label": "Super Admin",
        "workspace_section": "health_dna",
        **extra,
    }


@login_required
@never_cache
def health_genetic_list(request):
    _require_super_admin(request.user)
    query = request.GET.get("q", "").strip()[:160]
    dogs = []
    if query:
        condition = Q(name__icontains=query) | Q(slug__icontains=query) | Q(kennel__name__icontains=query)
        try:
            condition |= Q(pk=uuid.UUID(query))
        except (ValueError, AttributeError):
            pass
        dogs = list(
            Dog.objects.filter(condition).select_related("kennel")
            .order_by("name", "pk")[:40]
        )
    latest = (
        HealthRecord.objects.filter(evidence_document__staff_review_only=True)
        .select_related("dog", "evidence_document")
        .order_by("-created_at")[:20]
    )
    return render(request, "accounts/health_genetic_admin.html", _context(
        request, query=query, dogs=dogs, recent=latest,
    ))


@login_required
@never_cache
def health_genetic_dog(request, pk):
    _require_super_admin(request.user)
    dog = get_object_or_404(Dog.objects.select_related("kennel"), pk=pk)
    form = HistoricalHealthEvidenceForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        category = data["record_type"]
        provenance = data["source_reference"].strip()
        notes = (
            "Staff-reviewed original evidence: " + provenance
            + ("; Laboratory: " + data["laboratory"].strip() if data.get("laboratory") else "")
            + ("; URL: " + data["source_url"] if data.get("source_url") else "")
            + ("; Notes: " + data["notes"].strip() if data.get("notes") else "")
        )
        with transaction.atomic():
            evidence = DogDocument.objects.create(
                dog=dog,
                title=(data["test_type"].strip() + " · staff-reviewed evidence")[:220],
                document_type=(
                    DogDocument.DocumentType.HEALTH if category == "health"
                    else DogDocument.DocumentType.DNA
                ),
                file=data["attachment"],
                is_public=False,
                staff_review_only=True,
                submitted_by=request.user,
            )
            health = HealthRecord.objects.create(
                dog=dog,
                test_type=data["test_type"].strip(),
                result=readable_health_result(data["result"]),
                tested_on=data["tested_on"],
                verification_state=VerificationState.HEALTH_VERIFIED,
                notes=notes,
                # Approved health/marker text appears automatically. DNA breed
                # composition remains private until owner summary consent.
                is_public=category != "breed",
                evidence_document=evidence,
            )
            if category == "breed":
                BreedDNAReport.objects.create(
                    health_record=health,
                    evidence_document=evidence,
                    provider=data["laboratory"].strip(),
                    cane_corso_percentage=data["cane_corso_percentage"],
                    composition=data["composition"],
                    consent_public_summary=False,
                    consent_full_report=False,
                )
            VerificationEvent.objects.create(
                dog=dog,
                health_record=health,
                state=VerificationState.HEALTH_VERIFIED,
                reviewer=request.user,
                note="Historical laboratory evidence independently reviewed by Super Admin. "
                     + ("No owner DNA publication consent." if category == "breed" else provenance),
            )
            record_audit(
                action=ModerationAudit.Action.VERIFICATION,
                actor=request.user, dog=dog,
                summary={
                    "kind": "historical_health_evidence",
                    "health_record_id": health.pk,
                    "document_id": evidence.pk,
                    "record_category": category,
                    "source_reference": provenance,
                    "owner_consent_public_summary": False if category == "breed" else None,
                    "owner_consent_full_report": False,
                },
                note="Historical health/genetic evidence reviewed; supporting file remains private.",
            )
            invalidate_public_content()
        messages.success(
            request,
            "Evidence saved. " + (
                "DNA breed composition is PRIVATE until the kennel owner submits publication consent."
                if category == "breed" else
                "The reviewed test result is available on a published dog's Health & DNA profile."
            ),
        )
        return redirect("accounts:health-genetic-dog", pk=dog.pk)
    history = (
        HealthRecord.objects.filter(dog=dog)
        .select_related("evidence_document", "breed_dna_report",
                        "breed_dna_report__evidence_document")
        .order_by("-created_at")[:60]
    )
    for record in history:
        (record.staff_public_status_code,
         record.staff_public_status_label,
         record.staff_public_status_reason) = publication_status(record, dog=dog)
    visible_dna_count = BreedDNAReport.objects.filter(
        health_record__dog=dog, consent_public_summary=True
    ).count()
    return render(request, "accounts/health_genetic_admin.html", _context(
        request, dog=dog, form=form, history=history,
        visible_dna_count=visible_dna_count,
    ))


@login_required
@require_POST
@never_cache
def withdraw_dna_publication(request, pk):
    _require_super_admin(request.user)
    dog = get_object_or_404(Dog, pk=pk)
    if request.POST.get("confirmation") != "hide_all":
        messages.error(request, "Confirm withdrawal before hiding public DNA details.")
        return redirect("accounts:health-genetic-dog", pk=dog.pk)
    with transaction.atomic():
        reports = list(
            BreedDNAReport.objects.select_for_update()
            .select_related("evidence_document", "health_record")
            .filter(health_record__dog=dog)
        )
        changed = []
        for report in reports:
            if report.consent_public_summary or report.consent_full_report or report.evidence_document.is_public:
                changed.append(report.pk)
                report.consent_public_summary = False
                report.consent_full_report = False
                report.save(update_fields=["consent_public_summary", "consent_full_report"])
                if report.evidence_document.is_public:
                    report.evidence_document.is_public = False
                    report.evidence_document.save(update_fields=["is_public"])
        if changed:
            record_audit(
                action=ModerationAudit.Action.VERIFICATION, actor=request.user, dog=dog,
                summary={"kind": "dna_publication_withdrawn", "report_ids": changed},
                note="All DNA breed-composition summaries and full reports hidden. "
                     "Only a new owner-authorized submission can restore publication.",
            )
            invalidate_public_content()
    messages.success(
        request, "DNA publication withdrawn for this dog. Private evidence was retained."
    )
    return redirect("accounts:health-genetic-dog", pk=dog.pk)
