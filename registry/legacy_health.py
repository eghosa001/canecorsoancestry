"""Render legacy health results as short text; do not claim missing DNA evidence."""

Never convert legacy prose into verified genotype results or DNA breed percentages.
"""
import re

from .genetic_health import SCREENING_RESULTS


_LEGACY_TITLE = re.compile(
    r"^\s*purity\s+verification\s*/\s*health\s+test\s*$",
    re.IGNORECASE,
)
_MARKER_RESULT = re.compile(
    r"^\s*(DSRA|NCL1|CMR1)\s*(?:[:=\-]\s*)?"
    r"(CLEAR|CARRIER|AFFECTED|AT RISK|INCONCLUSIVE|NOT TESTED)\s*$",
    re.IGNORECASE,
)
_BREED_CLAIM = re.compile(
    r"^\s*(?:[0-9]{1,3}(?:\.[0-9]{1,2})?%\s*)?Cane\s+Corso\s*$",
    re.IGNORECASE,
)


def legacy_mixed_health_rows(test_type, result, *, record_verified=False):
    """Split old mixed records and respect their staff health-review decision.

    The recorded screening status (e.g. Clear) and evidence verification are
    distinct. A reviewed health record can confirm its recorded marker statuses,
    but a breed percentage still needs the owner-consented DNA report.
    """
    if not _LEGACY_TITLE.fullmatch((test_type or "").strip()):
        return None
    rows = []
    seen = set()
    for piece in re.split(r"(?<!\d)\.(?!\d)|;|\n", (result or "").strip()):
        entry = piece.strip()
        if not entry:
            continue
        if _BREED_CLAIM.fullmatch(entry):
            if "breed" not in seen:
                rows.append({"test": "Breed purity", "result": "No DNA report", "verified": False})
                seen.add("breed")
            continue
        marker = _MARKER_RESULT.fullmatch(entry)
        if marker:
            code = marker.group(1).upper()
            status = SCREENING_RESULTS[marker.group(2).lower()][0]
            if code not in seen:
                rows.append({"test": code, "result": status, "verified": record_verified})
                seen.add(code)
            else:
                # Conflicting claims cannot be silently resolved or shown as Clear.
                existing = next(row for row in rows if row["test"] == code)
                if existing["result"] != status:
                    existing["result"] = "Result unclear"
                    existing["verified"] = False
            continue
        # Unknown text stays visible, not silently discarded.
        rows.append({"test": "Other reported finding", "result": entry, "verified": False})
    return rows or [{"test": "Health screening", "result": "Result not provided", "verified": False}]
