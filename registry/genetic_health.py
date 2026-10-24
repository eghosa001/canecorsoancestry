"""Reviewed external laboratory genetic markers; never infer genetic clearance."""
from datetime import date

SCREENING_MARKERS = (
    ("DSRA", "Dental-Skeletal-Retinal Anomaly"),
    ("NCL1", "Neuronal Ceroid Lipofuscinosis 1"),
    ("CMR1", "Canine Multifocal Retinopathy 1"),
)
MARKER_CODES = frozenset(code for code, _ in SCREENING_MARKERS)
SCREENING_RESULTS = {
    "clear": ("Clear", "clear"),
    "carrier": ("Carrier", "carrier"),
    "affected": ("Affected", "affected"),
    "at risk": ("Affected", "affected"),
    "at risk / affected": ("Affected", "affected"),
    "inconclusive": ("Inconclusive", "other"),
    "not tested": ("Not tested", "untested"),
    "pending": ("Pending", "other"),
}
RESULT_CHOICES = (
    ("Clear", "Clear — no tested variant detected"),
    ("Carrier", "Carrier — one copy detected"),
    ("Affected", "Affected / at risk — two copies detected"),
    ("Inconclusive", "Inconclusive — no definitive result"),
    ("Not tested", "Not tested — only when explicitly stated in a report"),
)


def marker_status_rows(records):
    """Show only markers supported by actual published, evidence-reviewed results."""
    latest = {}
    for record in records:
        code = (record.test_type or "").strip().upper()
        if code not in MARKER_CODES or record.verification_state != "health":
            continue
        rank = (record.tested_on or date.min, record.created_at, record.pk or 0)
        if code not in latest or rank > latest[code][0]:
            latest[code] = (rank, record)
    rows = []
    for code, name in SCREENING_MARKERS:
        record = latest.get(code, (None, None))[1]
        if record is None:
            continue  # Missing evidence is not an observed negative or an explicit Not tested result.
        original = (record.result or "").strip()
        classified = SCREENING_RESULTS.get(original.lower())
        rows.append({
            "code": code, "name": name,
            "status": classified[0] if classified else (original or "Result unclear"),
            "tone": classified[1] if classified else "other",
        })
    return rows


def readable_health_result(value):
    """Normalize recognized labels without guessing the meaning of unfamiliar lab wording."""
    original = (value or "").strip()
    matched = SCREENING_RESULTS.get(original.lower())
    return matched[0] if matched else original


def unstructured_breed_claim(test_type):
    """Legacy free-text breed claims are not approved breed-composition reports.

    Prevent accidental public display of e.g. "100% Cane Corso. DSRA CLEAR"
    when no normalized, owner-authorized BreedDNAReport exists.
    """
    label = (test_type or "").strip().lower()
    return "breed" in label and any(
        word in label for word in ("dna", "composition", "identification", "purity")
    )
