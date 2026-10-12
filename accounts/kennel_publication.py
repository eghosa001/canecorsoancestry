"""Audited kennel-profile and dog-visibility controls for assigned moderators.

Public kennel profiles and the publication approval of dogs are independent.
A temporary moderation suppression never grants publication to an unapproved dog.
"""
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from registry.models import Dog, Kennel, ModerationAudit
from registry.permissions import can_review_submissions
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit


KENNEL_ACTIONS = {
    "show_all": (True, False),
    "hide_profile": (False, False),
    "hide_dogs": (True, True),
    "hide_all": (False, True),
}
MAX_SELECTED_DOGS = 40


def _require_moderator(user):
    if not can_review_submissions(user):
        raise PermissionDenied


@login_required
def kennel_publication_list(request):
    _require_moderator(request.user)
    query = request.GET.get("q", "").strip()[:160]
    kennels = Kennel.objects.all()
    if query:
        kennels = kennels.filter(
            Q(name__icontains=query) | Q(slug__icontains=query)
            | Q(city__icontains=query) | Q(country__icontains=query)
        )
    kennels = kennels.annotate(
        dog_count=Count("dogs", distinct=True),
    ).order_by("name")
    page = Paginator(kennels, 24).get_page(request.GET.get("page"))
    return render(request, "accounts/kennel_publication_list.html", {
        "kennels": page.object_list, "page_obj": page, "query": query,
    })


@login_required
def kennel_publication_detail(request, pk):
    _require_moderator(request.user)
    kennel = get_object_or_404(Kennel, pk=pk)
    dogs = kennel.dogs.order_by("name", "pk")
    page = Paginator(dogs, MAX_SELECTED_DOGS).get_page(request.GET.get("page"))
    return render(request, "accounts/kennel_publication_detail.html", {
        "kennel": kennel,
        "page_obj": page,
        "dogs": page.object_list,
        "approved_total": kennel.dogs.filter(is_public=True).count(),
        "hidden_total": kennel.dogs.filter(hidden_by_moderation=True).count(),
        "version": kennel.updated_at.isoformat(),
    })


@login_required
@require_POST
def kennel_publication_change(request, pk):
    _require_moderator(request.user)
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "").strip()
    if action not in KENNEL_ACTIONS:
        messages.error(request, "Select a valid kennel publication option.")
        return redirect("accounts:kennel-publication-detail", pk=pk)
    if request.POST.get("confirm") != "yes" or len(reason) < 5:
        messages.error(request, "Confirm the change and provide a reason (at least 5 characters).")
        return redirect("accounts:kennel-publication-detail", pk=pk)

    with transaction.atomic():
        kennel = get_object_or_404(Kennel.objects.select_for_update(), pk=pk)
        if request.POST.get("version") != kennel.updated_at.isoformat():
            messages.error(request, "This kennel changed. Reload and review its current visibility.")
            return redirect("accounts:kennel-publication-detail", pk=pk)
        before = {"is_public": kennel.is_public, "hide_dogs": kennel.hide_dogs}
        new_public, new_hide_dogs = KENNEL_ACTIONS[action]
        if (new_public, new_hide_dogs) == (kennel.is_public, kennel.hide_dogs):
            messages.info(request, "The kennel already has this visibility.")
            return redirect("accounts:kennel-publication-detail", pk=pk)
        kennel.is_public = new_public
        kennel.hide_dogs = new_hide_dogs
        kennel.save(update_fields=["is_public", "hide_dogs", "updated_at"])
        record_audit(
            action=ModerationAudit.Action.RECORD_CHANGED,
            actor=request.user, kennel=kennel,
            summary={
                "kind": "kennel_publication",
                "action": action,
                "before": before,
                "after": {"is_public": kennel.is_public, "hide_dogs": kennel.hide_dogs},
            },
            note=reason,
        )
        invalidate_public_content()
    messages.success(request, "Kennel publication settings saved. Dog approval states were preserved.")
    return redirect("accounts:kennel-publication-detail", pk=pk)


@login_required
@require_POST
def kennel_dogs_visibility_change(request, pk):
    """Suppress/restore selected dogs without bypassing their approval state."""
    _require_moderator(request.user)
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "").strip()
    if action not in {"hide", "restore"}:
        messages.error(request, "Select Hide or Restore for the selected dogs.")
        return redirect("accounts:kennel-publication-detail", pk=pk)
    if request.POST.get("confirm") != "yes" or len(reason) < 5:
        messages.error(request, "Confirm the change and provide a reason (at least 5 characters).")
        return redirect("accounts:kennel-publication-detail", pk=pk)
    raw_ids = request.POST.getlist("dog_ids")
    if not raw_ids or len(raw_ids) > MAX_SELECTED_DOGS:
        messages.error(request, "Select between 1 and 40 dogs from this page.")
        return redirect("accounts:kennel-publication-detail", pk=pk)
    try:
        selected_ids = {UUID(value) for value in raw_ids}
    except (ValueError, TypeError, AttributeError):
        messages.error(request, "One of the selected dogs was invalid.")
        return redirect("accounts:kennel-publication-detail", pk=pk)
    if len(selected_ids) != len(raw_ids):
        messages.error(request, "The selection contained duplicate dog records.")
        return redirect("accounts:kennel-publication-detail", pk=pk)

    with transaction.atomic():
        kennel = get_object_or_404(Kennel.objects.select_for_update(), pk=pk)
        if request.POST.get("version") != kennel.updated_at.isoformat():
            messages.error(request, "This kennel changed. Reload before updating its dogs.")
            return redirect("accounts:kennel-publication-detail", pk=pk)
        dogs = list(Dog.objects.select_for_update().filter(
            kennel=kennel, pk__in=selected_ids,
        ))
        if len(dogs) != len(selected_ids):
            messages.error(request, "Some selected dogs no longer belong to this kennel.")
            return redirect("accounts:kennel-publication-detail", pk=pk)

        hide = action == "hide"
        changed = [dog for dog in dogs if dog.hidden_by_moderation != hide]
        if changed:
            timestamp = timezone.now()
            Dog.objects.filter(pk__in=[dog.pk for dog in changed]).update(
                hidden_by_moderation=hide, updated_at=timestamp,
            )
            for dog in changed:
                record_audit(
                    action=ModerationAudit.Action.RECORD_CHANGED,
                    actor=request.user, kennel=kennel, dog=dog,
                    summary={
                        "kind": "kennel_dog_visibility",
                        "action": action,
                        "before": {"hidden_by_moderation": not hide, "is_public": dog.is_public},
                        "after": {"hidden_by_moderation": hide, "is_public": dog.is_public},
                    },
                    note=reason,
                )
            invalidate_public_content()
    messages.success(
        request, f"{len(changed)} dog(s) updated. Private or unapproved records remain private."
        if changed else "Selected dogs already had the requested visibility.",
    )
    return redirect("accounts:kennel-publication-detail", pk=pk)
