"""Current staff review alerts, derived from the authoritative unresolved queues.

No per-user notification rows are created: a case disappears when it is resolved,
so a reviewer never has to dismiss stale review notifications.
"""
from django.urls import reverse

from registry.models import DisputeCase, Submission
from registry.permissions import can_manage_verification, can_review_submissions


def staff_review_alerts(user):
    """Return role-appropriate pending case links for the shared site header."""
    if not can_review_submissions(user):
        return None

    submissions = Submission.objects.filter(status=Submission.Status.PENDING)
    disputes = DisputeCase.objects.filter(
        status__in=(DisputeCase.Status.OPEN, DisputeCase.Status.REVIEWING)
    )
    submission_count = submissions.count()
    dispute_count = disputes.count()

    items = []
    for case in submissions.select_related("dog", "kennel", "litter", "document").order_by(
        "-created_at"
    )[:4]:
        subject = (
            (case.dog.name if case.dog_id else "")
            or (case.kennel.name if case.kennel_id else "")
            or (case.litter.code if case.litter_id else "")
            or (case.document.title if case.document_id else "")
            or "Submitted record"
        )
        items.append({
            "title": subject,
            "detail": case.get_kind_display(),
            "url": reverse("accounts:moderation-submission", args=(case.pk,)),
        })

    for case in disputes.select_related("dog").order_by("-created_at")[:2]:
        items.append({
            "title": case.dog.name,
            "detail": "Dispute · " + case.get_reason_display(),
            "url": (reverse("accounts:moderation") + "?focus_dispute=" + str(case.pk)
                    + "#dispute-" + str(case.pk)),
        })

    # Only the Super Admin can decide protected pedigree proposals. Their
    # source of truth is the immutable audit log rather than Submission.
    protected_pending = False
    if can_manage_verification(user):
        from accounts.direct_dog_edit import pending_proposals_for_dashboard

        proposals = pending_proposals_for_dashboard(limit=1)
        if proposals:
            protected_pending = True
            event = proposals[0]
            items.append({
                "title": event.dog.name,
                "detail": "Protected pedigree change · Super Admin",
                "url": reverse("accounts:dog-direct-edit", args=(event.dog_id,)),
            })

    total = submission_count + dispute_count + int(protected_pending)
    # Protected proposals can exceed the single preview; never present the
    # lower bound as an exact count.
    display_count = (
        "99+" if total > 99 else
        f"{total}+" if protected_pending else str(total)
    )
    return {
        "total": total,
        "display_count": display_count,
        "has_pending": total > 0,
        "protected_pending": protected_pending,
        "submission_count": submission_count,
        "dispute_count": dispute_count,
        "items": items,
        "aria_label": (
            f"At least {total} pending review cases"
            if protected_pending else f"{total} pending review cases"
        ),
    }
