"""Display recorded canine hip/elbow scores in plain English without changing evidence.

Only explicit scoring codes are expanded. An unrecognized report stays unchanged.
"""
import re


HIP_GRADES = {
    "A": ("Normal hips", "The X-ray screening found no signs of hip dysplasia.", "normal"),
    "B": ("Hips are close to normal", "The hips were graded near-normal. Ask a veterinarian what this means for the dog.", "borderline"),
    "C": ("Mild hip dysplasia", "The screening found mild signs of hip dysplasia.", "caution"),
    "D": ("Moderate hip dysplasia", "The screening found moderate signs of hip dysplasia.", "caution"),
    "E": ("Severe hip dysplasia", "The screening found severe signs of hip dysplasia.", "caution"),
}

ELBOW_GRADES = {
    "0": ("Normal elbows", "The X-ray screening found no signs of elbow dysplasia.", "normal"),
    "1": ("Mild elbow changes", "The screening found mild changes associated with elbow dysplasia.", "caution"),
    "2": ("Moderate elbow changes", "The screening found moderate changes associated with elbow dysplasia.", "caution"),
    "3": ("Severe elbow changes", "The screening found severe changes associated with elbow dysplasia.", "caution"),
}

# HDA ED0, HD-A / ED-0, Hip dysplasia: A, Elbow dysplasia: 0.
# A generic "clear" or "healthy" is never inferred to be an A/0 grade.
HIP_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:HD|HIP\s+DYSPLASIA)\s*[-:=]?\s*(?:GRADE\s*)?([A-E])(?![A-Z0-9])",
    re.IGNORECASE,
)
ELBOW_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:ED|ELBOW\s+DYSPLASIA)\s*[-:=]?\s*(?:GRADE\s*)?([0-3])(?![A-Z0-9])",
    re.IGNORECASE,
)
HIP_LABEL = re.compile(r"^(?:HD|HIP\s+(?:DYSPLASIA|SCORE|GRADE))$", re.IGNORECASE)
ELBOW_LABEL = re.compile(r"^(?:ED|ELBOW\s+(?:DYSPLASIA|SCORE|GRADE))$", re.IGNORECASE)


def describe_orthopaedic_result(test_type, result):
    """Return zero, one or two displayed assessments for explicit grading codes.

    This is purely presentation logic, not an evidence-verification decision.
    """
    label = (test_type or "").strip()
    value = (result or "").strip()
    combined = label + " " + value
    hip_match = HIP_PATTERN.search(combined)
    elbow_match = ELBOW_PATTERN.search(combined)
    hip_grade = hip_match.group(1).upper() if hip_match else None
    elbow_grade = elbow_match.group(1) if elbow_match else None

    if hip_grade is None and HIP_LABEL.fullmatch(label) and re.fullmatch(r"[A-E]", value, re.IGNORECASE):
        hip_grade = value.upper()
    if elbow_grade is None and ELBOW_LABEL.fullmatch(label) and re.fullmatch(r"[0-3]", value):
        elbow_grade = value

    rows = []
    if hip_grade:
        headline, explanation, tone = HIP_GRADES[hip_grade]
        rows.append({
            "test": "Hip dysplasia screening",
            "headline": headline,
            "explanation": explanation,
            "grade": "HD-" + hip_grade,
            "grade_label": "Grade " + hip_grade,
            "tone": tone,
        })
    if elbow_grade:
        headline, explanation, tone = ELBOW_GRADES[elbow_grade]
        rows.append({
            "test": "Elbow dysplasia screening",
            "headline": headline,
            "explanation": explanation,
            "grade": "ED-" + elbow_grade,
            "grade_label": "Grade " + elbow_grade,
            "tone": tone,
        })
    return rows
