"""Audited direct changes to canonical dogs, independent of member submissions.

All mutable dog-profile fields and related records use the same transaction and
before/after audit. The super admin can accept or reverse a moderator change.
"""
import hashlib
import json
import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.forms import inlineformset_factory
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from registry.models import (
    Dog, DogAlias, DogDocument, DogExternalKey, DogIdentityNumber, DogImage,
    DogRegistration, DogSource, DogTitle, HealthRecord, Kennel, Litter,
    ModerationAudit,
)
from registry.permissions import can_manage_verification, can_review_submissions
from registry.services import record_audit
from .forms import validate_document_upload, validate_image_upload, normalize_image_upload


DOG_FIELDS = (
    "name", "sex", "date_of_birth", "colour", "country", "bloodline",
    "kennel", "sire", "dam", "litter", "bio", "verification_state",
)
RELATED = {
    "aliases": (DogAlias, ("name",)),
    "titles": (DogTitle, ("name", "source_text")),
    "registrations": (DogRegistration, ("authority", "number", "issued_on")),
    "identity_numbers": (DogIdentityNumber, ("kind", "value")),
    "external_keys": (DogExternalKey, ("namespace", "key")),
    "images": (DogImage, ("image", "caption", "is_primary", "sort_order")),
    "health_records": (HealthRecord, ("test_type", "result", "tested_on", "verification_state", "notes")),
    "sources": (DogSource, ("source_type", "title", "source_url", "document", "notes", "raw_payload")),
    "documents": (DogDocument, ("title", "document_type", "file", "is_public")),
}


def _find_reference(model, text, *, fields):
    text = (text or "").strip()
    if not text:
        return None
    try:
        key = uuid.UUID(text)
    except ValueError:
        key = None
    if key:
        match = model.objects.filter(pk=key).first()
        if match is None:
            raise ValidationError("No record has that UUID.")
        return match
    query = Q()
    for field in fields:
        query |= Q(**{field + "__iexact": text})
    matches = list(model.objects.filter(query).distinct()[:2])
    if not matches:
        raise ValidationError("No matching record. Use an exact name, code or UUID.")
    if len(matches) > 1:
        raise ValidationError("Ambiguous record. Enter its UUID instead.")
    return matches[0]


class DirectDogEditForm(forms.ModelForm):
    sire_ref = forms.CharField(required=False, label="Sire name or UUID")
    dam_ref = forms.CharField(required=False, label="Dam name or UUID")
    kennel_ref = forms.CharField(required=False, label="Kennel name or UUID")
    litter_ref = forms.CharField(required=False, label="Litter code or UUID")
    reason = forms.CharField(
        min_length=5, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required. Explain the evidence or reason for the live change.",
    )

    class Meta:
        model = Dog
        fields = tuple(field for field in DOG_FIELDS if field not in {"sire", "dam", "kennel", "litter"})
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "bio": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        dog = self.instance
        if dog.pk and not self.is_bound:
            for name in ("sire", "dam", "kennel", "litter"):
                self.fields[name + "_ref"].initial = str(getattr(dog, name + "_id") or "")

    def clean(self):
        data = super().clean()
        reference_fields = {
            "sire": (Dog, ("name", "slug", "registrations__number")),
            "dam": (Dog, ("name", "slug", "registrations__number")),
            "kennel": (Kennel, ("name", "slug")),
            "litter": (Litter, ("code",)),
        }
        for field, (model, lookups) in reference_fields.items():
            try:
                selected = _find_reference(model, data.get(field + "_ref"), fields=lookups)
            except ValidationError as exc:
                self.add_error(field + "_ref", exc)
                continue
            if selected and field == "sire" and selected.sex == Dog.Sex.FEMALE:
                self.add_error("sire_ref", "A sire cannot be recorded as female.")
            if selected and field == "dam" and selected.sex == Dog.Sex.MALE:
                self.add_error("dam_ref", "A dam cannot be recorded as male.")
            data[field] = selected
        return data


class ManagedImageForm(forms.ModelForm):
    make_primary = forms.BooleanField(required=False, label="Primary photo")

    class Meta:
        model = DogImage
        fields = ("image", "caption", "sort_order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.fields["make_primary"].initial = self.instance.is_primary

    def clean_image(self):
        upload = self.cleaned_data.get("image")
        if isinstance(upload, UploadedFile):
            validate_image_upload(upload)
            return normalize_image_upload(upload)
        return upload



class ManagedSourceForm(forms.ModelForm):
    class Meta:
        model = DogSource
        fields = RELATED["sources"][1]

    def clean_document(self):
        upload = self.cleaned_data.get("document")
        if isinstance(upload, UploadedFile):
            validate_document_upload(upload)
        return upload


class ManagedDocumentForm(forms.ModelForm):
    class Meta:
        model = DogDocument
        fields = RELATED["documents"][1]

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if isinstance(upload, UploadedFile):
            validate_document_upload(upload)
        return upload


FORMSETS = {
    key: inlineformset_factory(
        Dog, model, fields=(tuple(f for f in fields if f != "is_primary") if key == "images" else fields), form=(
            ManagedImageForm if key == "images" else
            ManagedSourceForm if key == "sources" else
            ManagedDocumentForm if key == "documents" else forms.ModelForm
        ),
        extra=0, can_delete=True,
    )
    for key, (model, fields) in RELATED.items()
}


def _edit_formsets(dog, data=None, files=None):
    return {
        name: factory(data=data, files=files, instance=dog, prefix=name)
        for name, factory in FORMSETS.items()
    }


def _safe_value(value):
    if hasattr(value, "name") and hasattr(value, "storage"):
        return value.name or ""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _snapshot(dog):
    base = {
        Dog._meta.get_field(field).attname: _safe_value(
            getattr(dog, Dog._meta.get_field(field).attname)
        )
        for field in DOG_FIELDS
    }
    related = {}
    for name, (model, fields) in RELATED.items():
        rows = []
        for item in model.objects.filter(dog=dog).order_by("pk"):
            row = {"id": item.pk}
            for field in fields:
                column = model._meta.get_field(field).attname
                row[column] = _safe_value(getattr(item, column))
            rows.append(row)
        related[name] = rows
    return {"dog": base, "related": related}


def _save_formsets(dog, sets):
    image_forms = [
        form for form in sets["images"].forms
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
        and (form.instance.pk or form.has_changed())
    ]
    if sum(bool(form.cleaned_data.get("make_primary")) for form in image_forms) > 1:
        raise ValidationError("Only one photograph can be selected as primary.")
    chosen_primary = None
    for name, formset in sets.items():
        # Delete first, so unique registration/identity values can be reused.
        for form in formset.forms:
            if form.cleaned_data and form.cleaned_data.get("DELETE") and form.instance.pk:
                if name in {"health_records", "sources"} and form.instance.verification_events.exists():
                    raise ValidationError("This record has verification history. Update it rather than deleting linked evidence.")
                form.instance.delete()
        for form in formset.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            if not form.instance.pk and not form.has_changed():
                continue
            item = form.save(commit=False)
            item.dog = dog
            if name == "images":
                upload = form.cleaned_data.get("image")
                if isinstance(upload, UploadedFile):
                    item.content_sha256 = hashlib.sha256(upload.read()).hexdigest()
                    upload.seek(0)
            item.full_clean(validate_constraints=name != "images")
            item.save()
            if name == "images" and form.cleaned_data.get("make_primary"):
                chosen_primary = item.pk
    DogImage.objects.filter(dog=dog, is_primary=True).update(is_primary=False)
    if chosen_primary is not None:
        DogImage.objects.filter(dog=dog, pk=chosen_primary).update(is_primary=True)


def _restore(dog, target):
    for field, value in target["dog"].items():
        setattr(dog, field, value)
    dog.full_clean()
    dog.save()
    for name, (model, fields) in RELATED.items():
        incoming = {row["id"]: row for row in target["related"][name]}
        existing = {item.pk: item for item in model.objects.filter(dog=dog)}
        for pk, item in existing.items():
            if pk not in incoming:
                if name in {"health_records", "sources"} and item.verification_events.exists():
                    raise ValidationError("Reversal would erase later verification history. Use a new super-admin override instead.")
                item.delete()
        if name == "images":
            model.objects.filter(dog=dog, is_primary=True).update(is_primary=False)
        for pk, row in incoming.items():
            item = existing.get(pk) or model(pk=pk, dog=dog)
            for field in fields:
                column = model._meta.get_field(field).attname
                setattr(item, column, row[column])
            item.full_clean(validate_constraints=name != "images")
            item.save()


def _revision_events(dog=None):
    events = ModerationAudit.objects.filter(
        action=ModerationAudit.Action.RECORD_CHANGED,
        summary__kind="direct_dog_edit",
    ).select_related("dog", "actor")
    if dog is not None:
        events = events.filter(dog=dog)
    return events.order_by("-created_at")


def _review_states(events):
    ids = [str(event.pk) for event in events]
    decisions = ModerationAudit.objects.filter(
        action=ModerationAudit.Action.RECORD_CHANGED,
        summary__original_audit_id__in=ids,
    ).order_by("-created_at")
    states = {}
    for audit in decisions:
        key = audit.summary.get("original_audit_id")
        if key and key not in states:
            states[key] = audit.summary.get("kind")
    for event in events:
        event.review_state = states.get(str(event.pk), "")
    return events


@login_required
def dog_edit_list(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    q = request.GET.get("q", "").strip()[:160]
    dogs = Dog.objects.select_related("kennel").order_by("name")
    if q:
        filter_query = Q(name__icontains=q) | Q(slug__icontains=q) | Q(registrations__number__icontains=q)
        try:
            filter_query |= Q(pk=uuid.UUID(q))
        except ValueError:
            pass
        dogs = dogs.filter(filter_query).distinct()[:30]
    else:
        dogs = dogs.none()
    revisions = list(_revision_events()[:60])
    _review_states(revisions)
    return render(request, "accounts/direct_dog_list.html", {
        "dogs": dogs, "query": q, "revisions": revisions,
        "is_owner": can_manage_verification(request.user),
    })


@login_required
def dog_direct_edit(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(
        Dog.objects.select_related("sire", "dam", "kennel", "litter"), pk=pk
    )
    owner = can_manage_verification(request.user)
    if dog.is_record_locked and not owner:
        raise PermissionDenied("This record is locked by the super admin.")
    data = request.POST if request.method == "POST" else None
    files = request.FILES if request.method == "POST" else None
    form = DirectDogEditForm(data, instance=dog)
    sets = _edit_formsets(dog, data, files)
    if request.method == "POST":
        valid = form.is_valid()
        for formset in sets.values():
            valid = formset.is_valid() and valid
        if valid:
            try:
                with transaction.atomic():
                    locked = Dog.objects.select_for_update().get(pk=pk)
                    # Prevent overwriting another moderator's recent save.
                    if request.POST.get("version") != locked.updated_at.isoformat():
                        raise ValidationError("The dog changed while this form was open. Reload and review the latest values.")
                    if locked.is_record_locked and not owner:
                        raise PermissionDenied("This record is locked by the super admin.")
                    before = _snapshot(locked)
                    for field in DOG_FIELDS:
                        if field in {"kennel", "sire", "dam", "litter"}:
                            setattr(locked, field, form.cleaned_data[field])
                        else:
                            setattr(locked, field, form.cleaned_data[field])
                    locked.full_clean()
                    locked.save()
                    _save_formsets(locked, sets)
                    after = _snapshot(locked)
                    if before != after:
                        record_audit(
                            action=ModerationAudit.Action.RECORD_CHANGED,
                            actor=request.user, dog=locked, kennel=locked.kennel,
                            summary={"kind": "direct_dog_edit", "before": before, "after": after,
                                     "is_owner": owner},
                            note=form.cleaned_data["reason"],
                        )
                messages.success(request, "Dog information saved live with an audit trail. Super admin may review or reverse it.")
                return redirect("accounts:dog-direct-edit", pk=pk)
            except (IntegrityError, ValidationError) as exc:
                form.add_error(None, str(exc))
    revisions = list(_revision_events(dog)[:25])
    _review_states(revisions)
    return render(request, "accounts/direct_dog_edit.html", {
        "dog": dog, "form": form, "formsets": sets, "revisions": revisions,
        "owner": owner, "version": dog.updated_at.isoformat(),
    })


@login_required
@require_POST
def dog_review_edit(request, pk, audit_id):
    if not can_manage_verification(request.user):
        raise PermissionDenied
    decision = request.POST.get("decision")
    note = request.POST.get("reason", "").strip()
    if decision not in {"accept", "revert"} or len(note) < 5:
        messages.error(request, "Choose an action and explain your decision (at least 5 characters).")
        return redirect("accounts:dog-direct-edit", pk=pk)
    try:
        with transaction.atomic():
            dog = get_object_or_404(Dog.objects.select_for_update(), pk=pk)
            event = get_object_or_404(_revision_events(dog), pk=audit_id)
            already_reviewed = ModerationAudit.objects.filter(
                action=ModerationAudit.Action.RECORD_CHANGED,
                summary__original_audit_id=str(event.pk),
            ).exists()
            if already_reviewed:
                raise ValidationError("This revision has already been reviewed.")
            if decision == "revert":
                current = _snapshot(dog)
                if current != event.summary["after"]:
                    raise ValidationError(
                        "A later change has modified this record. To preserve those changes, review the newer revisions or make an explicit super-admin override."
                    )
                _restore(dog, event.summary["before"])
            record_audit(
                action=ModerationAudit.Action.RECORD_CHANGED,
                actor=request.user, dog=dog, kennel=dog.kennel,
                summary={
                    "kind": "direct_dog_revert" if decision == "revert" else "direct_dog_review",
                    "original_audit_id": str(event.pk),
                    "review_action": decision,
                    "before": event.summary["after"] if decision == "revert" else None,
                    "after": event.summary["before"] if decision == "revert" else None,
                },
                note=note,
            )
        messages.success(request, "Change reverted with a permanent record." if decision == "revert" else "Moderator change reviewed and accepted.")
    except (ValidationError, IntegrityError) as exc:
        messages.error(request, str(exc))
    return redirect("accounts:dog-direct-edit", pk=pk)
