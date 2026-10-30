"""One source of truth for whether a health result reaches the public dog page.

The saved is_public flag is only a publication request. The dog profile
also enforces dog visibility, breed-DNA owner consent, and safe structured
test labels. Keep staff badges consistent with those actual display rules.
"""
from .genetic_health import unstructured_breed_claim
from .legacy_health import legacy_mixed_health_rows
from .models import VerificationState


def publication_status(record, *, dog=None):
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
        if not report.consent_public_summary:
            return (
                "consent", "Not visible — owner consent required",
                "The owner has not authorized a public breed-DNA summary. "
                "The private report must not be published.",
            )
        if record.verification_state != VerificationState.HEALTH_VERIFIED:
            return (
                "unverified_dna", "Not visible — DNA review required",
                "Only verified, owner-authorized breed-DNA reports display publicly.",
            )
        return (
            "published", "Visible on public profile",
            "The authorized breed-DNA summary appears in the Health & DNA section.",
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
            "results. Do not publish a breed-purity percentage without owner consent.",
        )

    if unstructured_breed_claim(record.test_type):
        return (
            "needs_structuring", "Not visible — correct the result",
            "This older breed-DNA claim has no owner-authorized structured "
            "breed report. Record independently verified clinical or genetic "
            "test findings individually; do not publish unconsented DNA percentages.",
        )
    return (
        "published", "Visible on public profile",
        "This result is eligible to appear in the dog's Health & DNA section.",
    )
