"""One source of truth for whether a health result reaches the public dog page.

The saved is_public flag is only a publication request. The dog profile
also enforces dog visibility, breed-DNA owner consent, and safe structured
test labels. Keep staff badges consistent with those actual display rules.
"""
from .genetic_health import unstructured_breed_claim
from .legacy_health import legacy_mixed_health_rows
from .models import ModerationAudit, VerificationState


def staff_authorized_breed_record_ids(dog):
    """Last explicit staff publication decision per breed summary, from audit.

    This does not alter or impersonate the kennel owner's consent. A Super
    Admin publication decision is separately attributable and reversible.
    """
    decisions = {}
    entries = (
        ModerationAudit.objects.filter(
            dog=dog,
            action=ModerationAudit.Action.VERIFICATION,
            summary__kind="staff_breed_dna_publication",
        ).order_by("pk").values_list("summary", flat=True)
    )
    for entry in entries.iterator(chunk_size=200):
        if not isinstance(entry, dict):
            continue
        record_id, public = entry.get("health_record_id"), entry.get("public")
        if type(record_id) is int and type(public) is bool:
            decisions[record_id] = public
    return {pk for pk, is_public in decisions.items() if is_public}


def breed_publication_allowed(report, *, staff_authorized_ids=None):
    """True for member-consented or separately staff-authorized typed summaries."""
    if report.consent_public_summary:
        return True
    if staff_authorized_ids is None:
        staff_authorized_ids = staff_authorized_breed_record_ids(report.health_record.dog)
    return report.health_record_id in staff_authorized_ids


def publication_status(record, *, dog=None, staff_authorized_ids=None):
    """Return (code, short status, explanation) without mutating any record.

    A record's private evidence file never becomes a public attachment.
    Call with select_related("breed_dna_report", "dog__kennel") for lists.
    """
    dog = dog or record.dog
    if not record.is_public:
        return (
            "private", "Held privately",
            "This health result is not approved for public display.",
        )
    if not dog.is_effectively_public:
        return (
            "dog_hidden", "Not visible on site",
            "This dog's public profile is not visible. Check dog publication, "
            "moderation restrictions, and kennel visibility.",
        )

    report = getattr(record, "breed_dna_report", None)
    if report is not None:
        if not breed_publication_allowed(report, staff_authorized_ids=staff_authorized_ids):
            return (
                "authorization", "Not visible — publication decision required",
                "A Super Admin can make this reviewed breed-DNA summary public. "
                "The private source report always stays private.",
            )
        if record.verification_state != VerificationState.HEALTH_VERIFIED:
            return (
                "unverified_dna", "Not visible — DNA review required",
                "Only verified breed-DNA summaries approved for public display appear.",
            )
        return (
            "published", "Visible on public profile",
            "The approved breed-DNA summary appears in the Health & DNA section.",
        )

    legacy_rows = legacy_mixed_health_rows(
        record.test_type, record.result,
        record_verified=record.verification_state == VerificationState.HEALTH_VERIFIED,
    )
    if legacy_rows is not None and not legacy_rows:
        if (
            record.verification_state == VerificationState.HEALTH_VERIFIED
            and record.evidence_document_id
        ):
            return (
                "summary_only", "Only evidence notice visible",
                "The source certificate was reviewed, but no separate clinical "
                "or genetic test result has been transcribed. Use Add a missing "
                "health result to enter supported values from that report.",
            )
        return (
            "needs_structuring", "Not visible — enter health test results",
            "This legacy mixed breed/health record has no shareable test-specific "
            "results. Publish breed composition only via a reviewed, structured DNA report.",
        )

    if unstructured_breed_claim(record.test_type):
        return (
            "needs_structuring", "Not visible — correct the result",
            "This older breed-DNA claim has no structured, publication-approved "
            "breed report. Review genuine DNA evidence before displaying percentages.",
        )
    return (
        "published", "Visible on public profile",
        "This result is eligible to appear in the dog's Health & DNA section.",
    )
