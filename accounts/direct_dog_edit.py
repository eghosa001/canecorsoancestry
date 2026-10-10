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
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from registry.models import (
    Dog, DogAlias, DogDocument, DogExternalKey, DogIdentityNumber, DogImage,
    DogRegistration, DogSource, DogTitle, HealthRecord, Kennel, Litter,
    ModerationAudit,
)
from registry.public_freshness import invalidate_public_content
from registry.permissions import can_manage_verification, can_review_submissions
from registry.services import record_audit, moderation_dog_ids
from .forms import validate_document_upload, validate_image_upload, normalize_image_upload


DOG_FIELDS = (
    "name", "sex", "date_of_birth", "colour", "country", "bloodline",
    "kennel", "sire", "dam", "litter", "bio", "verification_state",
)
# Changing published identity or ancestry must require independent Super Admin
# confirmation rather than appearing publicly merely because a staff form saved.
PROTECTED_DOG_FIELDS = frozenset({
    "sex", "date_of_birth", "sire", "dam", "litter", "kennel",
    "verification_state",
})
PROTECTED_RELATED = frozenset({
    "registrations", "identity_numbers", "external_keys", "health_records", "sources",
})


def _candidate_change(field, value):
    if field in {"sire", "dam", "kennel", "litter"}:
        return str(value.pk) if value is not None else None
    return _safe_value(value)


def _current_change(dog, field):
    column = Dog._meta.get_field(field).attname
    return _safe_value(getattr(dog, column))


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
    sire_ref = forms.CharField(required=False, label="Sire name or UUID", widget=forms.TextInput(attrs={"data-admin-parent-lookup": "", "data-parent-sex": "male", "autocomplete": "off", "placeholder": "Search sire by name or registration"}))
    dam_ref = forms.CharField(required=False, label="Dam name or UUID", widget=forms.TextInput(attrs={"data-admin-parent-lookup": "", "data-parent-sex": "female", "autocomplete": "off", "placeholder": "Search dam by name or registration"}))
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
                if name in {"sire", "dam"}:
                    parent = getattr(dog, name)
                    if parent:
                        # Progressive enhancement: render the readable name in
                        # the staff picker, while posting the unambiguous UUID.
                        self.fields[name + "_ref"].widget.attrs.update({
                            "data-current-parent-name": parent.name,
                            "data-current-parent-id": str(parent.pk),
                        })

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
    if chosen_primary is not None:
        # Make the primary-image change explicit. Text edits must never
        # silently clear the profile thumbnail.
        DogImage.objects.filter(dog=dog, is_primary=True).exclude(pk=chosen_primary).update(is_primary=False)
        DogImage.objects.filter(dog=dog, pk=chosen_primary).update(is_primary=True)
    elif not DogImage.objects.filter(dog=dog, is_primary=True).exists():
        # If the former primary was deleted, pick an existing remaining photo.
        replacement = DogImage.objects.filter(dog=dog).order_by("sort_order", "created_at").first()
        if replacement:
            DogImage.objects.filter(pk=replacement.pk).update(is_primary=True)


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
    ).filter(
        Q(summary__kind="direct_dog_edit") | Q(summary__kind="direct_dog_proposal")
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


def pending_proposals_for_dashboard(*, limit=12, batch_size=80):
    """Find unresolved ancestry proposals regardless of their age.

    A fixed newest-80 query can conceal an older proposal whenever many later
    edits have already been resolved. Walk the audit log in bounded keyset
    batches, never loading the full audit trail into application memory.
    Review decisions remain immutable audit rows, not mutable flags.
    """
    pending = []
    cursor = None
    while len(pending) < limit:
        candidates = ModerationAudit.objects.filter(
            action=ModerationAudit.Action.RECORD_CHANGED,
            summary__kind="direct_dog_proposal",
            dog__isnull=False,
        )
        if cursor is not None:
            created_at, pk = cursor
            candidates = candidates.filter(
                Q(created_at__lt=created_at)
                | Q(created_at=created_at, pk__lt=pk)
            )
        batch = list(
            candidates.select_related("dog", "actor")
            .order_by("-created_at", "-pk")[:batch_size]
        )
        if not batch:
            break
        _review_states(batch)
        pending.extend(
            event for event in batch if not event.review_state
        )
        if len(batch) < batch_size:
            break
        cursor = (batch[-1].created_at, batch[-1].pk)
    return pending[:limit]


@login_required
def dog_edit_list(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.GET.get("proposals") == "1":
        proposal_query = (
            ModerationAudit.objects.filter(
                action=ModerationAudit.Action.RECORD_CHANGED,
                summary__kind="direct_dog_proposal",
            )
            .select_related("dog", "actor")
            .order_by("-created_at")
        )
        page = Paginator(proposal_query, 30).get_page(request.GET.get("page"))
        proposals = list(page.object_list)
        _review_states(proposals)
        return render(request, "accounts/direct_dog_list.html", {
            "dogs": [], "query": "", "revisions": proposals,
            "is_owner": can_manage_verification(request.user),
            "history_deferred": False, "proposal_page": page,
            "show_proposals": True,
        })
    q = request.GET.get("q", "").strip()[:160]
    ids = moderation_dog_ids(q, limit=30) if q else []
    # One narrow query after bounded ID discovery. Preserve relevance order;
    # never run DISTINCT across all dogs and registration joins.
    found = {
        dog.pk: dog for dog in Dog.objects.filter(pk__in=ids)
        .select_related("kennel")
    }
    dogs = [found[pk] for pk in ids if pk in found]
    # Dog lookup should not synchronously load the full revision history on
    # every query. Staff may request it explicitly after finding the dog.
    show_history = not q or request.GET.get("history") == "1"
    revisions = list(_revision_events()[:25]) if show_history else []
    if revisions:
        _review_states(revisions)
    return render(request, "accounts/direct_dog_list.html", {
        "dogs": dogs, "query": q, "revisions": revisions,
        "is_owner": can_manage_verification(request.user),
        "history_deferred": bool(q and not show_history),
    })


@login_required
@require_POST
def dog_set_public_visibility(request, pk):
    """Only the Super Admin deliberately publishes direct Django Admin records.

    Creating a canonical dog through Advanced Admin is NOT member moderation.
    There is no member-submission approval to process for this record.
    Keep the act of publication separate, explicit, version-safe and audited.
    """
    if not can_manage_verification(request.user):
        raise PermissionDenied
    action = request.POST.get("action", "")
    note = request.POST.get("reason", "").strip()
    if action not in {"publish", "unpublish"}:
        messages.error(request, "Choose Publish or Unpublish.")
        return redirect("accounts:dog-direct-edit", pk=pk)
    if request.POST.get("confirm_visibility") != "yes" or len(note) < 5:
        messages.error(
            request,
            "Confirm the visibility change and provide a reason of at least 5 characters.",
        )
        return redirect("accounts:dog-direct-edit", pk=pk)

    try:
        with transaction.atomic():
            dog = get_object_or_404(Dog.objects.select_for_update(), pk=pk)
            if request.POST.get("version") != dog.updated_at.isoformat():
                raise ValidationError(
                    "This dog was edited since the publication page loaded. "
                    "Reload and review the latest record before publishing."
                )
            make_public = action == "publish"
            if dog.is_public == make_public:
                messages.info(request, "This dog already has the requested visibility.")
                return redirect("accounts:dog-direct-edit", pk=pk)
            # No automatic 'verified' status is granted by publication.
            # Respect ancestry cycle/identity validations before exposing facts.
            dog.full_clean()
            before = _snapshot(dog)
            dog.is_public = make_public
            dog.save(update_fields=["is_public", "updated_at"])
            after = _snapshot(dog)
            record_audit(
                action=ModerationAudit.Action.RECORD_CHANGED,
                actor=request.user, dog=dog, kennel=dog.kennel,
                summary={
                    "kind": "direct_dog_edit",
                    "publication_action": action,
                    "before": before,
                    "after": after,
                    "is_owner": True,
                },
                note=note,
            )
            invalidate_public_content()
    except (ValidationError, IntegrityError) as exc:
        messages.error(request, f"Publication was not changed: {exc}")
        return redirect("accounts:dog-direct-edit", pk=pk)

    if make_public:
        if DogImage.objects.filter(dog_id=pk).exists():
            messages.success(
                request,
                "Dog published successfully. Its profile and photograph are now eligible for public search and browsing.",
            )
        else:
            messages.warning(
                request,
                "Dog published successfully and can be found by exact name or direct profile link. "
                "The main dog gallery lists only dogs with photographs. "
                "Add a genuine dog photo in the Images section to include it in the general browse list.",
            )
    else:
        messages.success(request, "Dog unpublished. It is no longer visible on public profiles or search.")
    return redirect("accounts:dog-direct-edit", pk=pk)


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
                    # Only canonical facts that are deliberately low-risk may
                    # save directly for a moderator. Sensitive published
                    # ancestry goes through a separate human approval.
                    if locked.is_public and not owner:
                        protected = {
                            field: _candidate_change(field, form.cleaned_data[field])
                            for field in PROTECTED_DOG_FIELDS
                            if _current_change(locked, field)
                            != _candidate_change(field, form.cleaned_data[field])
                        }
                        restricted_related = [
                            name for name in PROTECTED_RELATED if sets[name].has_changed()
                        ]
                        if restricted_related:
                            raise ValidationError(
                                "Changes to registration, identity, source or health evidence "
                                "on a published dog require Super Admin editing. "
                                "Do not combine them with ordinary direct edits."
                            )
                        if protected:
                            ordinary_changed = [
                                field for field in DOG_FIELDS
                                if field not in PROTECTED_DOG_FIELDS
                                and _current_change(locked, field)
                                != _candidate_change(field, form.cleaned_data[field])
                            ]
                            changed_formsets = [
                                name for name, group in sets.items() if group.has_changed()
                            ]
                            if ordinary_changed or changed_formsets:
                                raise ValidationError(
                                    "Send protected ancestry changes for review separately "
                                    "from ordinary details, photos or related records. "
                                    "No changes were published."
                                )
                            candidate = Dog.objects.get(pk=locked.pk)
                            for field, value in protected.items():
                                setattr(candidate, Dog._meta.get_field(field).attname, value)
                            candidate.full_clean()
                            before_protected = {
                                field: _current_change(locked, field)
                                for field in protected
                            }
                            record_audit(
                                action=ModerationAudit.Action.RECORD_CHANGED,
                                actor=request.user, dog=locked, kennel=locked.kennel,
                                summary={
                                    "kind": "direct_dog_proposal",
                                    "before_protected": before_protected,
                                    "proposed_changes": protected,
                                    "base_version": locked.updated_at.isoformat(),
                                },
                                note=form.cleaned_data["reason"],
                            )
                            messages.success(
                                request,
                                "Protected pedigree changes sent to Super Admin for "
                                "approval. The public dog record is unchanged."
                            )
                            return redirect("accounts:dog-direct-edit", pk=pk)
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
                        invalidate_public_content()
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
    if decision not in {"accept", "revert", "approve", "reject"} or len(note) < 5:
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
            if event.summary.get("kind") == "direct_dog_proposal":
                if decision not in {"approve", "reject"}:
                    raise ValidationError("Choose Approve or Reject for a pending proposal.")
                if decision == "approve":
                    for field, original in event.summary["before_protected"].items():
                        if _current_change(dog, field) != original:
                            raise ValidationError(
                                "These ancestry values changed after the proposal. "
                                "Review the latest dog record and resubmit instead."
                            )
                    before = _snapshot(dog)
                    for field, value in event.summary["proposed_changes"].items():
                        setattr(dog, Dog._meta.get_field(field).attname, value)
                    dog.full_clean()
                    dog.save()
                    after = _snapshot(dog)
                    invalidate_public_content()
                else:
                    before = after = None
                record_audit(
                    action=ModerationAudit.Action.RECORD_CHANGED,
                    actor=request.user, dog=dog, kennel=dog.kennel,
                    summary={
                        "kind": "direct_dog_proposal_approved" if decision == "approve"
                                else "direct_dog_proposal_rejected",
                        "original_audit_id": str(event.pk),
                        "before": before, "after": after,
                    },
                    note=note,
                )
                messages.success(
                    request,
                    "Protected pedigree changes approved and published."
                    if decision == "approve" else
                    "Proposed pedigree changes rejected; public data was unchanged."
                )
                return redirect("accounts:dog-direct-edit", pk=pk)
            if decision not in {"accept", "revert"}:
                raise ValidationError("Only Accept or Revert applies to completed live edits.")
            if decision == "revert":
                current = _snapshot(dog)
                if current != event.summary["after"]:
                    raise ValidationError(
                        "A later change has modified this record. To preserve those changes, review the newer revisions or make an explicit super-admin override."
                    )
                _restore(dog, event.summary["before"])
                invalidate_public_content()
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


@login_required
def dog_parent_suggestions(request):
    """Private staff lookup, including unpublished ancestors. Never return them publicly."""
    if not can_review_submissions(request.user):
        raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    sex = request.GET.get("sex", "")
    if sex not in {Dog.Sex.MALE, Dog.Sex.FEMALE}:
        return JsonResponse({"results": []})
    if len(query) < 2:
        return JsonResponse({"results": []})
    ids = moderation_dog_ids(query, limit=25, fuzzy=False)
    found = {
        dog.pk: dog for dog in Dog.objects.filter(
            pk__in=ids, sex__in=(sex, Dog.Sex.UNKNOWN),
        ).select_related("kennel").prefetch_related("registrations")
    }
    results = []
    for pk in ids:
        dog = found.get(pk)
        if not dog:
            continue
        registrations = [str(r.number) for r in dog.registrations.all() if r.number][:2]
        results.append({
            "id": str(dog.pk),
            "name": dog.name,
            "kennel": dog.kennel.name if dog.kennel_id else "",
            "registration": ", ".join(registrations),
            "dob": dog.date_of_birth.isoformat() if dog.date_of_birth else "",
            "is_public": dog.is_public,
        })
        if len(results) == 12:
            break
    return JsonResponse({"results": results})
