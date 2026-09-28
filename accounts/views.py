from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from registry.models import (
    Dog,
    DogDocument,
    Kennel,
    Litter,
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
    duplicate_candidates,
    merge_dogs,
    reject_submission,
)

from pedigrees.services import (
    PedigreeCycleError,
    inbreeding_coefficient,
    pedigree_generations,
    repeated_ancestors,
)

from .forms import (
    DocumentVisibilityForm,
    DogCorrectionForm,
    DogDocumentSubmissionForm,
    DogImageSubmissionForm,
    DogSubmissionForm,
    KennelClaimForm,
    KennelEditForm,
    LitterSubmissionForm,
    MergeDogsForm,
    ReviewSubmissionForm,
    VerificationEventForm,
)


def _date_value(value):
    return value.isoformat() if value else ""


@login_required
def submission_list(request):
    submissions = request.user.ancestry_submissions.select_related(
        "dog", "kennel", "litter", "document", "reviewed_by"
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
                "litter_id": str(form.cleaned_data["litter"].pk)
                if form.cleaned_data["litter"]
                else None,
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
                "litter_id": str(cleaned["litter"].pk) if cleaned["litter"] else None,
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
    memberships = request.user.kennel_memberships.select_related("kennel")
    kennel_ids = list(memberships.values_list("kennel_id", flat=True))
    editable_kennel_ids = {
        membership.kennel_id
        for membership in memberships
        if membership.role in {"owner", "editor"}
    }

    items = DogDocument.objects.filter(
        Q(submitted_by=request.user) | Q(dog__kennel_id__in=kennel_ids)
    ).select_related("dog__kennel", "submitted_by").distinct()

    document_type = request.GET.get("type", "").strip()
    visibility = request.GET.get("visibility", "").strip()
    if document_type:
        items = items.filter(document_type=document_type)
    if visibility == "public":
        items = items.filter(is_public=True)
    elif visibility == "private":
        items = items.filter(is_public=False)

    pending_visibility_ids = set(
        Submission.objects.filter(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            status=Submission.Status.PENDING,
            document__in=items,
        ).values_list("document_id", flat=True)
    )
    return render(
        request,
        "accounts/documents.html",
        {
            "documents": items,
            "document_types": DogDocument.DocumentType.choices,
            "selected_type": document_type,
            "selected_visibility": visibility,
            "pending_visibility_ids": pending_visibility_ids,
            "editable_kennel_ids": editable_kennel_ids,
        },
    )


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
        "submitted_by", "dog", "kennel", "litter", "document"
    )
    return render(
        request,
        "accounts/moderation_queue.html",
        {
            "pending": pending,
            "merge_form": MergeDogsForm(),
            "verification_form": VerificationEventForm(),
            "duplicate_candidates": duplicate_candidates(),
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



@login_required
def my_pedigrees(request):
    kennel_ids = request.user.kennel_memberships.values_list("kennel_id", flat=True)
    dogs = (
        Dog.objects.filter(kennel_id__in=kennel_ids)
        .select_related("kennel", "sire", "dam")
        .order_by("name")
    )
    rows = [
        {
            "dog": dog,
            "parent_count": int(bool(dog.sire_id)) + int(bool(dog.dam_id)),
        }
        for dog in dogs
    ]
    return render(
        request,
        "accounts/my_pedigrees.html",
        {"rows": rows},
    )


@login_required
def member_pedigree_detail(request, pk):
    kennel_ids = request.user.kennel_memberships.values_list("kennel_id", flat=True)
    dog = get_object_or_404(
        Dog.objects.select_related("kennel", "sire", "dam"),
        pk=pk,
        kennel_id__in=kennel_ids,
    )
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in {4, 6, 8, 10} else 4

    try:
        coi_percent = inbreeding_coefficient(dog, public_only=False) * 100
        cycle_error = ""
    except PedigreeCycleError:
        coi_percent = None
        cycle_error = "This pedigree contains a parent cycle and cannot be analysed safely."

    return render(
        request,
        "accounts/member_pedigree_detail.html",
        {
            "dog": dog,
            "generations": generations,
            "generation_options": (4, 6, 8, 10),
            "layers": pedigree_generations(dog, generations, public_only=False),
            "repeated": repeated_ancestors(dog, generations, public_only=False),
            "coi_percent": coi_percent,
            "cycle_error": cycle_error,
        },
    )


@login_required
def my_litters(request):
    memberships = request.user.kennel_memberships.select_related("kennel")
    kennel_ids = list(memberships.values_list("kennel_id", flat=True))
    editable_kennel_ids = {
        membership.kennel_id
        for membership in memberships
        if membership.role in {"owner", "editor"}
    }
    litters = (
        Litter.objects.filter(kennel_id__in=kennel_ids)
        .select_related("kennel", "sire", "dam")
        .order_by("-date_of_birth", "code")
    )
    return render(
        request,
        "accounts/my_litters.html",
        {
            "litters": litters,
            "editable_kennel_ids": editable_kennel_ids,
            "can_create_litter": bool(editable_kennel_ids),
        },
    )


@login_required
def submit_litter(request):
    form = LitterSubmissionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        kennel = form.cleaned_data["kennel"]
        if not can_edit_kennel(request.user, kennel):
            raise PermissionDenied
        cleaned = form.cleaned_data
        Submission.objects.create(
            kind=Submission.Kind.LITTER_CREATE,
            submitted_by=request.user,
            kennel=kennel,
            payload={
                "code": cleaned["code"],
                "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                "date_of_birth": _date_value(cleaned["date_of_birth"]),
                "notes": cleaned["notes"],
            },
            notes=cleaned["review_notes"],
        )
        messages.success(request, "Litter submitted for moderator review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Litter management",
            "title": "Submit a litter",
            "intro": "New litters are reviewed before they become canonical records and start private.",
            "button_label": "Submit litter",
        },
    )


@login_required
def edit_litter(request, pk):
    litter = get_object_or_404(Litter.objects.select_related("kennel"), pk=pk)
    if not can_edit_kennel(request.user, litter.kennel):
        raise PermissionDenied

    form = LitterSubmissionForm(
        request.POST or None,
        user=request.user,
        kennel=litter.kennel,
        litter=litter,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        if cleaned["kennel"] != litter.kennel:
            form.add_error("kennel", "An existing litter cannot be moved to another kennel.")
        else:
            Submission.objects.create(
                kind=Submission.Kind.LITTER_EDIT,
                submitted_by=request.user,
                kennel=litter.kennel,
                litter=litter,
                payload={
                    "code": cleaned["code"],
                    "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                    "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                    "date_of_birth": _date_value(cleaned["date_of_birth"]),
                    "notes": cleaned["notes"],
                },
                notes=cleaned["review_notes"],
            )
            messages.success(request, "Litter changes submitted for moderator review.")
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Litter management",
            "title": f"Suggest changes to {litter.code}",
            "intro": "The public/canonical litter stays unchanged until a moderator approves the correction.",
            "button_label": "Submit litter changes",
        },
    )


@login_required
def claim_kennel(request, pk):
    kennel = get_object_or_404(Kennel, pk=pk)
    if request.user.kennel_memberships.filter(kennel=kennel).exists():
        messages.info(request, "Your account is already linked to this kennel.")
        return redirect("dashboard")
    if kennel.memberships.exists():
        messages.error(
            request,
            "This kennel is already linked to an account. Ownership changes require moderator assistance.",
        )
        return redirect("registry:kennel-detail", slug=kennel.slug)

    pending = Submission.objects.filter(
        kind=Submission.Kind.KENNEL_CLAIM,
        status=Submission.Status.PENDING,
        submitted_by=request.user,
        kennel=kennel,
    ).exists()
    if pending:
        messages.info(request, "You already have a pending ownership claim for this kennel.")
        return redirect("accounts:submissions")

    form = KennelClaimForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        Submission.objects.create(
            kind=Submission.Kind.KENNEL_CLAIM,
            submitted_by=request.user,
            kennel=kennel,
            payload={"relationship": form.cleaned_data["relationship"]},
            attachment=form.cleaned_data["evidence"] or "",
            notes=form.cleaned_data["notes"],
        )
        messages.success(request, "Kennel ownership claim submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Kennel ownership",
            "title": f"Claim {kennel.name}",
            "intro": "A moderator will verify your relationship to this kennel before owner access is granted.",
            "button_label": "Submit ownership claim",
            "multipart": True,
        },
    )


@login_required
def request_document_visibility(request, pk):
    document = get_object_or_404(
        DogDocument.objects.select_related("dog__kennel"),
        pk=pk,
    )
    if not can_edit_kennel(request.user, document.dog.kennel):
        raise PermissionDenied

    initial = {"is_public": document.is_public}
    form = DocumentVisibilityForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        desired = form.cleaned_data["is_public"]
        if desired == document.is_public:
            messages.info(request, "The document already has that visibility.")
            return redirect("accounts:documents")
        pending = Submission.objects.filter(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            status=Submission.Status.PENDING,
            document=document,
        ).exists()
        if pending:
            messages.info(request, "A visibility request for this document is already pending.")
            return redirect("accounts:documents")

        Submission.objects.create(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            submitted_by=request.user,
            dog=document.dog,
            kennel=document.dog.kennel,
            document=document,
            payload={"is_public": desired},
            notes=form.cleaned_data["notes"],
        )
        messages.success(request, "Document visibility change submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Document management",
            "title": f"Visibility · {document.title}",
            "intro": "Public/private visibility changes are moderated so evidence is not exposed accidentally.",
            "button_label": "Submit visibility request",
        },
    )
