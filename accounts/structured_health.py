"""A compact, evidence-backed staff editor for common canine test findings.

Each field represents a separate result. Never reinterpret historical mixed
text as verified markers; a reviewer selects the actual accepted source.
Breed composition is privately recorded after review and only published by
an explicit authorized moderator decision; owner consent remains unchanged.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest
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
from .health_sources import approved_health_submissions, accepted_health_documents


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
    dna_evidence_confirmed = forms.BooleanField(
        required=False,
        label="I verified that the accepted legacy Health/DNA certificate contains a laboratory breed-composition percentage.",
    )
    laboratory = forms.CharField(required=False, max_length=100, label="DNA testing laboratory")
    other_breeds = forms.CharField(
        required=False, max_length=2000, label="Other breeds (if percentage is below 100)",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Boxer: 7.5"}),
        help_text="One breed and its percentage per line; all breeds must total 100%.",
    )
    tested_on = forms.DateField(
        required=False, label="Date recorded (optional)",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reviewed = forms.BooleanField(
        label="I confirm these are the available recorded values for this dog. Without approved laboratory evidence, the public profile will label them Not independently verified.",
    )

    def __init__(self, *args, dog, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_submission"].queryset = approved_health_submissions(dog)
        self.fields["source_document"].queryset = accepted_health_documents(dog)

    def clean(self):
        data = super().clean()
        if data.get("source_submission") and data.get("source_document"):
            self.add_error(None, "Choose only one approved laboratory report, or leave both blank for unverified information.")
        data["has_approved_evidence"] = bool(data.get("source_submission") or data.get("source_document"))
        changed = any(data.get(name) for name in ("cmr1", "dsra", "ncl1", "hip", "elbow"))
        pct = data.get("cane_corso_percentage")
        if pct is not None:
            changed = True
            source = data.get("source_document")
            submission = data.get("source_submission")
            # An unsupported breed percentage is still publishable as
            # explicitly unverified owner/staff-reported information. Never
            # manufacture a BreedDNAReport or claim DNA-tested without proof.
            data["breed_report_verified"] = bool(
                (data.get("laboratory") or "").strip() and (
                    (source and (
                        source.document_type == DogDocument.DocumentType.DNA
                        or data.get("dna_evidence_confirmed")
                    ))
                    or (submission and (submission.payload or {}).get("evidence_type") == "breed")
                )
            )
            try:
                data["composition"] = parse_breed_composition(
                    pct, data.get("other_breeds") or "",
                )
            except ValidationError as exc:
                self.add_error("other_breeds", exc)
        # Lab/provider details belong only to breed composition. When a
        # reviewer is updating HD, ED or an individual genetic marker, empty
        # breed-composition fields must not block that unrelated result.
        if not changed:
            self.add_error(None, "Select at least one test value to change.")
        if data.get("tested_on") and data["tested_on"] > timezone.localdate():
            self.add_error("tested_on", "The report date cannot be in the future.")
        return data


def structured_rows(records):
    """Prepare compact read-only current values without trusting mixed legacy prose."""
    latest = {}
    for record in records:
        code = record.test_type.strip().upper()
        if code not in {"CMR1", "DSRA", "NCL1", "HD", "ED"}:
            continue
        # The latest staff correction is authoritative. Sorting primarily by
        # the lab date could resurrect an older, superseded public result after
        # a newer correction references an older laboratory report.
        if code not in latest or (record.created_at, record.pk) > (
            latest[code].created_at, latest[code].pk
        ):
            latest[code] = record
    return latest


@login_required
@require_POST
def save_structured_health(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog.objects.select_related("kennel"), pk=pk)
    intent = request.POST.get("intent", "save")
    if intent not in {"save", "publish"}:
        return HttpResponseBadRequest("Choose Save privately or Save & publish selected results.")
    publish_selected = intent == "publish"
    form = StructuredHealthForm(request.POST, dog=dog)
    if not form.is_valid():
        # Render the same staff workspace with the bound form. Redirecting
        # here discarded every value the reviewer had just entered on mobile.
        from .health_review import reviewed_dog_health

        request._structured_health_form_override = form
        messages.error(request, "Nothing was saved or published. Review the errors in the health editor.")
        return reviewed_dog_health(request, pk)
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
        elif document:
            document = get_object_or_404(
                DogDocument.objects.select_for_update(), pk=document.pk, dog=dog,
            )
        if document and document.is_public:
            document.is_public = False
            document.save(update_fields=["is_public"])
        source_key = (
            f"submission:{submission.pk}" if submission else
            f"document:{document.pk}" if document else "staff-reported:unverified"
        )
        evidence_verified = bool(data["has_approved_evidence"])
        verification_state = (
            VerificationState.HEALTH_VERIFIED if evidence_verified else VerificationState.COMMUNITY
        )
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
                and (previous.verification_state == VerificationState.HEALTH_VERIFIED
                     or previous.verification_state == verification_state)
            ):
                # Publishing a previously saved private result does not require
                # re-entering, duplicating or altering any other test.
                if publish_selected and not previous.is_public:
                    previous.is_public = True
                    previous.save(update_fields=["is_public"])
                    record_audit(
                        action=ModerationAudit.Action.VERIFICATION,
                        actor=request.user, dog=dog,
                        summary={
                            "kind": "structured_health_visibility",
                            "health_record_id": previous.pk, "public": True,
                            "source": source_key,
                        },
                        note="Staff published an existing result; evidence status is unchanged.",
                    )
                    updates += 1
                continue
            # Preserve the original approved row and its immutable evidence.
            # Carry forward the previous privacy choice BEFORE marking the old
            # row superseded; otherwise the replacement would be hidden too.
            new_visibility = publish_selected or (previous.is_public if previous else False)
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
                verification_state=verification_state,
                is_public=new_visibility,
                evidence_document=direct_document,
                notes=(
                    f"Structured staff health transcription from accepted {source_key}"
                    if evidence_verified else
                    "Staff-published available health information; laboratory evidence not verified"
                ),
            )
            if evidence_verified:
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
                    "public": new_visibility,
                    "evidence_verified": evidence_verified,
                    "superseded_health_record_id": previous.pk if previous else None,
                    "source": source_key,
                },
                note=(
                    "Staff saved evidence-backed individual test result; original document stays private."
                    if evidence_verified else
                    "Staff recorded available health information without laboratory verification."
                ),
            )
            existing[code] = record
            updates += 1

        pct = data.get("cane_corso_percentage")
        if pct is not None:
            if not data.get("breed_report_verified") or document is None:
                # No accepted DNA certificate supports this estimate. Publish
                # available information as a separate *unverified* record,
                # never as a BreedDNAReport or DNA-tested finding.
                label = "Cane Corso percentage (reported)"
                value = percentage_text(pct) + "% Cane Corso"
                previous = HealthRecord.objects.select_for_update().filter(
                    dog=dog, test_type=label,
                ).order_by("-created_at", "-pk").first()
                if (
                    previous and previous.result == value
                    and (not when or previous.tested_on == when)
                ):
                    if publish_selected and not previous.is_public:
                        previous.is_public = True
                        previous.save(update_fields=["is_public"])
                        updates += 1
                else:
                    new_visibility = publish_selected or (previous.is_public if previous else False)
                    if previous and previous.is_public:
                        previous.is_public = False
                        previous.save(update_fields=["is_public"])
                    record = HealthRecord.objects.create(
                        dog=dog, test_type=label, result=value,
                        tested_on=when, verification_state=VerificationState.COMMUNITY,
                        is_public=new_visibility,
                        notes="Staff-reported breed estimate; no accepted laboratory breed-composition evidence",
                    )
                    record_audit(
                        action=ModerationAudit.Action.VERIFICATION,
                        actor=request.user, dog=dog,
                        summary={
                            "kind": "reported_breed_estimate",
                            "health_record_id": record.pk,
                            "percentage": percentage_text(pct),
                            "source": source_key,
                            "evidence_verified": False,
                            "public": new_visibility,
                        },
                        note="Staff published a clearly unverified reported breed estimate; no DNA report was certified.",
                    )
                    updates += 1
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
                    if publish_selected:
                        rec.is_public = True
                    rec.save(update_fields=["result", "tested_on", "is_public"])
                else:
                    old = None
                    rec = HealthRecord.objects.create(
                        dog=dog, test_type="DNA breed composition",
                        result=percentage_text(pct) + "% Cane Corso",
                        tested_on=when, verification_state=VerificationState.HEALTH_VERIFIED,
                        is_public=publish_selected,
                        notes=f"Structured staff DNA transcription from accepted {source_key}; original evidence remains private",
                    )
                    BreedDNAReport.objects.create(
                        health_record=rec, evidence_document=document,
                        provider=data["laboratory"].strip(),
                        cane_corso_percentage=pct, composition=data["composition"],
                        consent_public_summary=False, consent_full_report=False,
                    )
                if publish_selected:
                    # A verified DNA report replaces an earlier unverified
                    # breed estimate on the public page, without deleting it.
                    HealthRecord.objects.filter(
                        dog=dog, test_type="Cane Corso percentage (reported)", is_public=True,
                    ).update(is_public=False)
                    # Public text summary only. Store a separate audited staff
                    # authorization; never set owner consent or expose the PDF.
                    record_audit(
                        action=ModerationAudit.Action.VERIFICATION,
                        actor=request.user, dog=dog,
                        summary={
                            "kind": "staff_breed_dna_publication",
                            "health_record_id": rec.pk, "public": True,
                            "basis": "admin_decision",
                        },
                        note="Authorized moderator published reviewed breed composition; private report stays restricted.",
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

        if updates:
            invalidate_public_content()
    if not updates:
        messages.info(request, "No values changed. Existing health information was retained.")
    else:
        messages.success(
            request, f"Saved {updates} health result{'s' if updates != 1 else ''}."
            + (
                " Selected results were published with their evidence status; all other health information was retained."
                if publish_selected else
                " New results are private; previously public corrections remain public. Other results were retained."
            )
        )
    return redirect("accounts:reviewed-dog-health", pk=pk)
