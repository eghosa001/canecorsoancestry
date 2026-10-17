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
}
RESULT_CHOICES = (
    ("Clear", "Clear — no tested variant detected"),
    ("Carrier", "Carrier — one copy detected"),
    ("Affected", "Affected / at risk — two copies detected"),
)


def marker_status_rows(records):
    """Most recent explicitly reviewed result only, or Not tested."""
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
        classified = SCREENING_RESULTS.get((record.result or "").strip().lower()) if record else None
        rows.append({
            "code": code, "name": name,
            "status": classified[0] if classified else "Not tested",
            "tone": classified[1] if classified else "untested",
        })
    return rows
