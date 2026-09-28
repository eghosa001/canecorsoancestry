from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    Dog,
    DogDocument,
    Notification,
    Submission,
    VerificationEvent,
)
from registry.permissions import (
    can_contribute_to_dog,
    can_contribute_to_kennel,
    can_edit_kennel,
)
from registry.services import (
    approve_submission,
    merge_dogs,
    reject_submission,
)

from .forms import (
    DogCorrectionForm,
    DogDocumentSubmissionForm,
    DogImageSubmissionForm,
    DogSubmissionForm,
    KennelEditForm,
    MergeDogsForm,
    ReviewSubmissionForm,
    VerificationEventForm,
)


def _date_value(value):
    return value.isoformat() if value else ""


@login_required
def submission_list(request):
    submissions = request.user.ancestry_submissions.select_related(
        "dog", "kennel", "reviewed_by"
    )
    return render(
        request,
        "accounts/submission_list.html",
        {"submissions": submissions},
    )


@login_required
def submit_dog(request):
    form = DogSubmissionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        kennel = form.cleaned_data["kennel"]
        if not can_contribute_to_kennel(request.user, kennel):
            raise PermissionDenied

        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=request.user,
            kennel=kennel,
            payload={
                "name": form.cleaned_data["name"],
                "sex": form.cleaned_data["sex"],
                "date_of_birth": _date_value(form.cleaned_data["date_of_birth"]),
                "colour": form.cleaned_data["colour"],
                "country": form.cleaned_data["country"],
                "bloodline": form.cleaned_data["bloodline"],
                "sire_id": str(form.cleaned_data["sire"].pk)
                if form.cleaned_data["sire"]
                else None,
                "dam_id": str(form.cleaned_data["dam"].pk)
                if form.cleaned_data["dam"]
                else None,
                "registration": form.cleaned_data["registration"],
                "bio": form.cleaned_data["bio"],
            },
            notes=form.cleaned_data["notes"],
        )
        messages.success(
            request,
            "Dog submission received. It will stay private until a moderator reviews it.",
        )
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Pedigree contribution",
            "title": "Submit a dog",
            "intro": "Submit a new canonical dog record for moderator review. This does not register the dog.",
            "button_label": "Submit for review",
        },
    )


@login_required
def submit_correction(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogCorrectionForm(
        request.POST or None,
        instance=dog,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        Submission.objects.create(
            kind=Submission.Kind.CORRECTION,
            submitted_by=request.user,
            dog=dog,
            kennel=dog.kennel,
            payload={
                "name": cleaned["name"],
                "sex": cleaned["sex"],
                "date_of_birth": _date_value(cleaned["date_of_birth"]),
                "colour": cleaned["colour"],
                "country": cleaned["country"],
                "bloodline": cleaned["bloodline"],
                "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                "bio": cleaned["bio"],
            },
            notes=cleaned["notes"],
        )
        messages.success(request, "Correction submitted for moderator review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Correction",
            "title": f"Suggest changes to {dog.name}",
            "intro": "Your edit is reviewed before the canonical pedigree record changes.",
            "button_label": "Submit correction",
            "dog": dog,
        },
    )


@login_required
def submit_image(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogImageSubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        Submission.objects.create(
            kind=Submission.Kind.IMAGE,
            submitted_by=request.user,
            dog=dog,
            kennel=dog.kennel,
            payload={
                "caption": form.cleaned_data["caption"],
                "is_primary": form.cleaned_data["is_primary"],
            },
            attachment=form.cleaned_data["attachment"],
            notes=form.cleaned_data["notes"],
        )
        messages.success(request, "Photo submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Dog media",
            "title": f"Submit a photo for {dog.name}",
            "intro": "Original uploads are retained; approved photos are attached to the canonical dog.",
            "button_label": "Submit photo",
            "multipart": True,
            "dog": dog,
        },
    )


@login_required
def submit_document(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogDocumentSubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        Submission.objects.create(
            kind=Submission.Kind.DOCUMENT,
            submitted_by=request.user,
            dog=dog,
            kennel=dog.kennel,
            payload={
                "title": form.cleaned_data["title"],
                "document_type": form.cleaned_data["document_type"],
                "is_public": form.cleaned_data["is_public"],
            },
            attachment=form.cleaned_data["attachment"],
            notes=form.cleaned_data["notes"],
        )
        messages.success(request, "Document submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Evidence",
            "title": f"Submit a document for {dog.name}",
            "intro": "Pedigree, health, DNA and external-registration evidence can be reviewed here.",
            "button_label": "Submit document",
            "multipart": True,
            "dog": dog,
        },
    )


@login_required
def edit_kennel(request, pk):
    membership = request.user.kennel_memberships.select_related("kennel").filter(
        kennel_id=pk
    ).first()
    if not membership or not can_edit_kennel(request.user, membership.kennel):
        raise PermissionDenied
    kennel = membership.kennel

    form = KennelEditForm(request.POST or None, instance=kennel)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        Submission.objects.create(
            kind=Submission.Kind.KENNEL,
            submitted_by=request.user,
            kennel=kennel,
            payload={
                "name": cleaned["name"],
                "country": cleaned["country"],
                "city": cleaned["city"],
                "description": cleaned["description"],
                "website": cleaned["website"],
            },
            notes=cleaned["notes"],
        )
        messages.success(request, "Kennel changes submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Kennel profile",
            "title": f"Edit {kennel.name}",
            "intro": "Owner/editor changes are reviewed before they replace the public kennel profile.",
            "button_label": "Submit kennel changes",
        },
    )


@login_required
def documents(request):
    kennel_ids = request.user.kennel_memberships.values_list("kennel_id", flat=True)
    items = DogDocument.objects.filter(
        Q(submitted_by=request.user) | Q(dog__kennel_id__in=kennel_ids)
    ).select_related("dog", "submitted_by").distinct()
    return render(request, "accounts/documents.html", {"documents": items})


@login_required
def notifications(request):
    if request.method == "POST":
        request.user.ancestry_notifications.filter(read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return redirect("accounts:notifications")
    items = request.user.ancestry_notifications.all()
    return render(request, "accounts/notifications.html", {"notifications": items})


@staff_member_required
def moderation_queue(request):
    pending = Submission.objects.filter(status=Submission.Status.PENDING).select_related(
        "submitted_by", "dog", "kennel"
    )
    return render(
        request,
        "accounts/moderation_queue.html",
        {
            "pending": pending,
            "merge_form": MergeDogsForm(),
            "verification_form": VerificationEventForm(),
        },
    )


@staff_member_required
def review_submission(request, pk, decision):
    if request.method != "POST":
        return redirect("accounts:moderation")
    submission = get_object_or_404(Submission, pk=pk)
    form = ReviewSubmissionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Review note was invalid.")
        return redirect("accounts:moderation")

    notes = form.cleaned_data["resolution_notes"]
    try:
        if decision == "approve":
            approve_submission(submission, request.user, notes)
            messages.success(request, "Submission approved.")
        elif decision == "reject":
            reject_submission(submission, request.user, notes)
            messages.success(request, "Submission rejected.")
        else:
            messages.error(request, "Unknown review action.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("accounts:moderation")


@staff_member_required
def merge_dogs_view(request):
    if request.method != "POST":
        return redirect("accounts:moderation")
    form = MergeDogsForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose two different dog records.")
        return redirect("accounts:moderation")

    canonical = form.cleaned_data["canonical"]
    duplicate = form.cleaned_data["duplicate"]
    try:
        history = merge_dogs(canonical, duplicate, performed_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Merged {history.retired_name} into {history.canonical_dog.name}.",
        )
    return redirect("accounts:moderation")



@staff_member_required
def verify_dog(request):
    if request.method != "POST":
        return redirect("accounts:moderation")
    form = VerificationEventForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Verification details were invalid.")
        return redirect("accounts:moderation")

    dog = form.cleaned_data["dog"]
    state = form.cleaned_data["state"]
    field_name = form.cleaned_data["field_name"].strip()
    VerificationEvent.objects.create(
        dog=dog,
        field_name=field_name,
        state=state,
        source=form.cleaned_data["source"],
        reviewer=request.user,
        note=form.cleaned_data["note"],
    )
    if not field_name:
        dog.verification_state = state
        dog.save(update_fields=("verification_state", "updated_at"))
    messages.success(request, "Verification event recorded.")
    return redirect("accounts:moderation")
