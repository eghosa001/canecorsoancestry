"""Identify independently recorded dogs for *manual* ancestry reconciliation.

Different names are never matched using fuzzy text. Only records from the
known Bellissimo and archival source namespaces with matching registration
digits, normalized full name and compatible sex qualify as candidates.
No pedigree, publication, or identity row is changed by this module.
"""
from collections import defaultdict
import re

from registry.models import (
    Dog, DogExternalKey, DogRegistration, DogSource, normalize_identity_name,
)

BELLISSIMO = "bellissimo-geni"
ARCHIVE = "canecorsopedigree.com"


def registration_digits(value):
    """Ignore registry prefix/punctuation, retaining the full numeric identity."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def audit_registration_backed_duplicates(*, max_display=20):
    """Return bounded evidence-backed candidates and an accurate total count.

    A single batched streaming query reads archive source evidence. Results are
    capped in memory; ambiguous/conflicted records are not labelled safe to
    reconcile. This is intentionally *not* a merge function.
    """
    max_display = max(0, min(int(max_display), 100))
    canonical_ids = list(
        DogExternalKey.objects.filter(namespace=BELLISSIMO)
        .values_list("dog_id", flat=True).distinct()
    )
    canonical = Dog.objects.in_bulk(canonical_ids)
    registration_index = defaultdict(set)
    for dog_id, number in DogRegistration.objects.filter(
        dog_id__in=canonical_ids
    ).values_list("dog_id", "number"):
        digits = registration_digits(number)
        if len(digits) >= 6:
            registration_index[digits].add(dog_id)

    results = []
    counted = set()
    totals = {"ready": 0, "needs_review": 0, "matched": 0}
    if not registration_index:
        return {"counts": totals, "candidates": results}

    rows = DogSource.objects.filter(
        dog__external_keys__namespace=ARCHIVE,
    ).values(
        "dog_id", "dog__slug", "dog__name", "dog__sex",
        "dog__is_public", "dog__date_of_birth", "dog__sire_id",
        "dog__dam_id", "dog__record_locked_at", "raw_payload",
    ).iterator(chunk_size=1000)

    for row in rows:
        payload = row["raw_payload"]
        if not isinstance(payload, dict):
            continue
        raw = str(payload.get("pedigree_number") or "")
        for field in re.split(r"[;,|]+|\s+/\s+", raw):
            digits = registration_digits(field)
            if digits not in registration_index:
                continue
            matched_ids = registration_index[digits]
            # One number appearing on multiple canonical dogs requires
            # independent identity review; do not claim it's safe.
            if len(matched_ids) != 1:
                continue
            canonical_id = next(iter(matched_ids))
            if row["dog_id"] == canonical_id:
                continue  # Already merged; never report a self-match.
            person = canonical[canonical_id]
            if (
                not person.is_public or not row["dog__is_public"]
                or person.sex not in (Dog.Sex.MALE, Dog.Sex.FEMALE)
                or person.sex != row["dog__sex"]
                or normalize_identity_name(person.name)
                != normalize_identity_name(row["dog__name"])
            ):
                continue

            key = (str(canonical_id), str(row["dog_id"]))
            if key in counted:
                continue
            counted.add(key)
            totals["matched"] += 1

            same_birth = (
                not person.date_of_birth or not row["dog__date_of_birth"]
                or person.date_of_birth == row["dog__date_of_birth"]
            )
            complementary_ancestry = (
                not person.sire_id and not person.dam_id
                and row["dog__sire_id"] and row["dog__dam_id"]
            )
            ready = (
                same_birth and complementary_ancestry
                and not person.record_locked_at
                and not row["dog__record_locked_at"]
            )
            status = "ready" if ready else "needs_review"
            totals[status] += 1
            if len(results) < max_display:
                results.append({
                    "canonical_id": str(canonical_id),
                    "canonical_slug": person.slug,
                    "source_id": str(row["dog_id"]),
                    "source_slug": row["dog__slug"],
                    "registration_digits": digits,
                    "status": status,
                    "reason": (
                        "Registration, full name and sex agree; canonical "
                        "parents missing and archive parents linked"
                        if ready
                        else "Check birth dates, parentage or locked records"
                    ),
                })

    return {"counts": totals, "candidates": results}
