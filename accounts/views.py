import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from registry.models import (
    DisputeCase,
    Dog,
    DogDocument,
    Kennel,
    Litter,
    ModerationAudit,
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
    duplicate_matches,
    merge_dogs,
    moderation_dog_search,
    record_audit,
    reject_submission,
    submission_diff,
)

from pedigrees.services import pedigree_analysis, pedigree_export_rows

from .forms import (
    BulkModerationForm,
    DisputeForm,
    DocumentVisibilityForm,
    DogCorrectionForm,
    DogDocumentSubmissionForm,
    DogImageSubmissionForm,
    DogSubmissionForm,
    DuplicateMatchForm,
    KennelClaimForm,
    KennelEditForm,
    LitterSubmissionForm,
    MemberSignUpForm,
    MergeDogsForm,
    ReviewSubmissionForm,
    VerificationEventForm,
)


def _date_value(value):
    return value.isoformat() if value else ""


def _member_dogs(user):
    kennel_ids = user.kennel_memberships.values_list("kennel_id", flat=True)
    return Dog.objects.filter(
        Q(kennel_id__in=kennel_ids)
        | Q(
            submissions__kind=Submission.Kind.DOG,
            submissions__status=Submission.Status.APPROVED,
            submissions__submitted_by=user,
        )
    ).distinct()


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = MemberSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to Cane Corso Ancestry.")
        return redirect("dashboard")

    return render(request, "registration/signup.html", {"form": form})


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
        if kennel and not can_contribute_to_kennel(request.user, kennel):
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
            "Dog submission received. It will not appear publicly unless an admin reviews and approves it.",
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
    pending = Submission.objects.filter(
        status=Submission.Status.PENDING
    ).select_related(
        "submitted_by",
        "dog",
        "kennel",
        "litter",
        "document",
        "assigned_to",
    )

    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "").strip()
    priority = request.GET.get("priority", "").strip()
    assignment = request.GET.get("assignment", "").strip()

    if query:
        pending = pending.filter(
            Q(submitted_by__username__icontains=query)
            | Q(dog__name__icontains=query)
            | Q(kennel__name__icontains=query)
            | Q(litter__code__icontains=query)
            | Q(document__title__icontains=query)
            | Q(notes__icontains=query)
        ).distinct()
    if kind in dict(Submission.Kind.choices):
        pending = pending.filter(kind=kind)
    if priority.isdigit() and int(priority) in dict(Submission.Priority.choices):
        pending = pending.filter(priority=int(priority))
    if assignment == "mine":
        pending = pending.filter(assigned_to=request.user)
    elif assignment == "unassigned":
        pending = pending.filter(assigned_to__isnull=True)

    pending_items = list(pending.order_by("-priority", "created_at")[:100])
    for item in pending_items:
        item.review_diff = submission_diff(item)
        age_days = max(0, (timezone.now() - item.created_at).days)
        item.age_days = age_days
        item.is_aging = age_days >= 7

    duplicate_form = DuplicateMatchForm(request.GET or None)
    duplicate_lookup_results = []
    duplicate_results = []
    duplicate_reference = None
    reference_id = request.GET.get("reference", "").strip()
    duplicate_query = request.GET.get("duplicate_q", "").strip()

    if reference_id:
        duplicate_reference = Dog.objects.select_related(
            "kennel", "sire", "dam"
        ).prefetch_related("registrations").filter(pk=reference_id).first()
        if duplicate_reference:
            duplicate_results = duplicate_matches(duplicate_reference)
    elif duplicate_query and duplicate_form.is_valid():
        duplicate_lookup_results = moderation_dog_search(
            duplicate_form.cleaned_data["duplicate_q"]
        )

    disputes = (
        DisputeCase.objects.filter(
            status__in=[DisputeCase.Status.OPEN, DisputeCase.Status.REVIEWING]
        )
        .select_related("dog", "opened_by", "assigned_to")
        .order_by("status", "created_at")[:50]
    )

    return render(
        request,
        "accounts/moderation_queue.html",
        {
            "pending": pending_items,
            "pending_total": pending.count(),
            "merge_form": MergeDogsForm(),
            "verification_form": VerificationEventForm(),
            "duplicate_candidates": duplicate_candidates(),
            "duplicate_form": duplicate_form,
            "duplicate_reference": duplicate_reference,
            "duplicate_lookup_results": duplicate_lookup_results,
            "duplicate_results": duplicate_results,
            "bulk_form": BulkModerationForm(),
            "disputes": disputes,
            "filters": {
                "q": query,
                "kind": kind,
                "priority": priority,
                "assignment": assignment,
            },
            "submission_kinds": Submission.Kind.choices,
            "priority_choices": Submission.Priority.choices,
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
    event = VerificationEvent.objects.create(
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
    record_audit(
        action=ModerationAudit.Action.VERIFICATION,
        actor=request.user,
        dog=dog,
        kennel=dog.kennel,
        summary={
            "verification_event_id": event.pk,
            "field_name": field_name,
            "state": state,
        },
        note=form.cleaned_data["note"],
    )
    messages.success(request, "Verification event recorded.")
    return redirect("accounts:moderation")



@login_required
def my_pedigrees(request):
    dogs = _member_dogs(request.user).select_related(
        "kennel", "sire", "dam"
    ).order_by("name")
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
    dog = get_object_or_404(
        _member_dogs(request.user).select_related("kennel", "sire", "dam"),
        pk=pk,
    )
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in {4, 6, 8, 10} else 4
    analysis = pedigree_analysis(dog, generations, public_only=False)

    return render(
        request,
        "accounts/member_pedigree_detail.html",
        {
            "dog": dog,
            "generations": generations,
            "generation_options": (4, 6, 8, 10),
            "analysis": analysis,
            "layers": analysis["layers"],
            "repeated": analysis["repeated"],
            "coi_percent": analysis["coi_percent"],
            "cycle_error": analysis["cycle_error"],
            "member_mode": True,
        },
    )


@login_required
def member_pedigree_export(request, pk):
    dog = get_object_or_404(
        _member_dogs(request.user).select_related("kennel"),
        pk=pk,
    )
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in {4, 6, 8, 10} else 4

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{dog.slug}-pedigree-{generations}g.csv"'
    )
    writer = csv.DictWriter(
        response,
        fieldnames=(
            "generation",
            "path",
            "dog_id",
            "name",
            "sex",
            "date_of_birth",
            "colour",
            "country",
            "kennel",
            "repeated",
            "path_contribution_percent",
        ),
    )
    writer.writeheader()
    writer.writerows(pedigree_export_rows(dog, generations, public_only=False))
    return response


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



@login_required
def open_dispute(request, pk):
    kennel_ids = request.user.kennel_memberships.values_list("kennel_id", flat=True)
    dog = get_object_or_404(
        Dog.objects.filter(Q(is_public=True) | Q(kennel_id__in=kennel_ids)).distinct(),
        pk=pk,
    )
    form = DisputeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        dispute = DisputeCase.objects.create(
            dog=dog,
            opened_by=request.user,
            reason=form.cleaned_data["reason"],
            details=form.cleaned_data["details"],
            attachment=form.cleaned_data["attachment"] or "",
        )
        record_audit(
            action=ModerationAudit.Action.DISPUTE_OPENED,
            actor=request.user,
            dog=dog,
            kennel=dog.kennel,
            dispute=dispute,
            summary={"reason": dispute.reason},
        )
        messages.success(request, "Review case opened. A moderator can now investigate it.")
        return redirect("accounts:my-disputes")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Dispute / review case",
            "title": f"Request review · {dog.name}",
            "intro": "Report a specific pedigree, identity, health, ownership or duplicate concern. Opening a case does not alter the canonical record.",
            "button_label": "Open review case",
            "multipart": True,
        },
    )


@login_required
def my_disputes(request):
    disputes = request.user.opened_ancestry_disputes.select_related(
        "dog", "assigned_to", "closed_by"
    )
    return render(
        request,
        "accounts/my_disputes.html",
        {"disputes": disputes},
    )


@staff_member_required
def bulk_moderation(request):
    if request.method != "POST":
        return redirect("accounts:moderation")

    form = BulkModerationForm(request.POST)
    submission_ids = request.POST.getlist("submission_ids")
    if not form.is_valid() or not submission_ids:
        messages.error(request, "Select at least one pending submission and a valid bulk action.")
        return redirect("accounts:moderation")

    action = form.cleaned_data["action"]
    note = form.cleaned_data["resolution_notes"].strip()
    now = timezone.now()

    with transaction.atomic():
        queryset = Submission.objects.select_for_update().filter(
            pk__in=submission_ids,
            status=Submission.Status.PENDING,
        )
        items = list(queryset)
        if not items:
            messages.info(request, "None of the selected submissions are still pending.")
            return redirect("accounts:moderation")

        if action == "reject":
            for item in items:
                reject_submission(item, request.user, note)
        elif action == "assign_me":
            queryset.update(
                assigned_to=request.user,
                review_started_at=now,
                updated_at=now,
            )
        elif action == "unassign":
            queryset.update(
                assigned_to=None,
                review_started_at=None,
                updated_at=now,
            )
        else:
            priority_map = {
                "priority_low": Submission.Priority.LOW,
                "priority_normal": Submission.Priority.NORMAL,
                "priority_high": Submission.Priority.HIGH,
                "priority_urgent": Submission.Priority.URGENT,
            }
            new_priority = priority_map.get(action)
            if new_priority is None:
                messages.error(request, "Unsupported bulk moderation action.")
                return redirect("accounts:moderation")
            queryset.update(priority=new_priority, updated_at=now)

        if action != "reject":
            record_audit(
                action=ModerationAudit.Action.SUBMISSION_BULK,
                actor=request.user,
                summary={
                    "action": action,
                    "count": len(items),
                    "submission_ids": [str(item.pk) for item in items],
                },
                note=note,
            )

    messages.success(request, f"Bulk moderation updated {len(items)} submission(s).")
    return redirect("accounts:moderation")


@staff_member_required
def review_dispute(request, pk, decision):
    if request.method != "POST":
        return redirect("accounts:moderation")

    note = request.POST.get("resolution_notes", "").strip()
    with transaction.atomic():
        dispute = get_object_or_404(
            DisputeCase.objects.select_for_update().select_related("dog", "opened_by"),
            pk=pk,
        )

        if decision == "assign":
            dispute.assigned_to = request.user
            dispute.status = DisputeCase.Status.REVIEWING
        elif decision == "resolve":
            if not note:
                messages.error(request, "A resolution note is required.")
                return redirect("accounts:moderation")
            dispute.status = DisputeCase.Status.RESOLVED
            dispute.resolution_notes = note
            dispute.closed_by = request.user
            dispute.closed_at = timezone.now()
        elif decision == "dismiss":
            if not note:
                messages.error(request, "A dismissal reason is required.")
                return redirect("accounts:moderation")
            dispute.status = DisputeCase.Status.DISMISSED
            dispute.resolution_notes = note
            dispute.closed_by = request.user
            dispute.closed_at = timezone.now()
        else:
            messages.error(request, "Unknown dispute action.")
            return redirect("accounts:moderation")

        dispute.save()
        record_audit(
            action=ModerationAudit.Action.DISPUTE_UPDATED,
            actor=request.user,
            dog=dispute.dog,
            kennel=dispute.dog.kennel,
            dispute=dispute,
            summary={"decision": decision, "status": dispute.status},
            note=note,
        )
        Notification.objects.create(
            user=dispute.opened_by,
            title=f"Review case {dispute.get_status_display().lower()}",
            message=f"Your review case for {dispute.dog.name} is now {dispute.get_status_display().lower()}.",
            link="/member/disputes/",
        )

    messages.success(request, "Dispute case updated.")
    return redirect("accounts:moderation")


@staff_member_required
def moderation_audit(request):
    events = ModerationAudit.objects.select_related(
        "actor", "dog", "kennel", "litter", "submission", "dispute"
    )

    query = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    actor = request.GET.get("actor", "").strip()

    if query:
        events = events.filter(
            Q(dog__name__icontains=query)
            | Q(kennel__name__icontains=query)
            | Q(litter__code__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(note__icontains=query)
        ).distinct()
    if action in dict(ModerationAudit.Action.choices):
        events = events.filter(action=action)
    if actor:
        events = events.filter(actor__username__icontains=actor)

    return render(
        request,
        "accounts/moderation_audit.html",
        {
            "events": events[:200],
            "actions": ModerationAudit.Action.choices,
            "filters": {"q": query, "action": action, "actor": actor},
        },
    )
