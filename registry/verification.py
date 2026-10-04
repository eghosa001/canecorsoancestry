import uuid
from datetime import date

from django.db import transaction
from django.utils import timezone

from .models import (
    Dog,
    DogIdentityNumber,
    DogImage,
    DogRegistration,
    EvidenceRequest,
    Litter,
    ModerationAudit,
    Submission,
    SubmissionEvidence,
    SubmissionRiskLevel,
    SubmissionVerificationStatus,
    VerificationFinding,
    VerificationRule,
    normalize_identity_name,
)


RISK_ORDER = {
    SubmissionRiskLevel.GREEN: 0,
    SubmissionRiskLevel.YELLOW: 1,
    SubmissionRiskLevel.RED: 2,
}


DEFAULT_RULES = {
    "payment_entitlement": (
        "Paid package entitlement mismatch",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_registration": (
        "Duplicate external registration number",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_microchip": (
        "Duplicate microchip number",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_identity": (
        "Possible duplicate dog identity",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_submission": (
        "Possible duplicate pending submission",
        SubmissionRiskLevel.YELLOW,
        False,
    ),
    "existing_identity_conflict": (
        "Existing dog identity conflict",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_photo": (
        "Duplicate identity photograph",
        SubmissionRiskLevel.YELLOW,
        False,
    ),
    "litter_dob_conflict": (
        "Litter date-of-birth conflict",
        SubmissionRiskLevel.RED,
        True,
    ),
    "litter_parent_conflict": (
        "Litter parentage conflict",
        SubmissionRiskLevel.RED,
        True,
    ),
    "litter_id_conflict": (
        "Litter identity conflict",
        SubmissionRiskLevel.RED,
        True,
    ),
    "litter_count_exceeded": (
        "Submitted puppies exceed declared litter size",
        SubmissionRiskLevel.RED,
        True,
    ),
    "unusually_large_litter": (
        "Unusually large declared litter",
        SubmissionRiskLevel.RED,
        True,
    ),
    "duplicate_litter": (
        "Possible duplicate litter",
        SubmissionRiskLevel.YELLOW,
        False,
    ),
    "missing_litter_core_data": (
        "Incomplete litter identity data",
        SubmissionRiskLevel.YELLOW,
        False,
    ),
    "pedigree_chronology": (
        "Pedigree chronology conflict",
        SubmissionRiskLevel.RED,
        True,
    ),
    "young_parent": (
        "Unusually young parent",
        SubmissionRiskLevel.YELLOW,
        False,
    ),
    "locked_ancestry_change": (
        "Published ancestry field change",
        SubmissionRiskLevel.RED,
        True,
    ),
}


def _date_value(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _id_text(value):
    return str(value) if value else ""


def _get_rule(code):
    defaults = DEFAULT_RULES[code]
    return VerificationRule.objects.filter(code=code).first(), defaults


def _add_finding(findings, *, submission, run_id, code, message, expected="", submitted="", metadata=None):
    rule, defaults = _get_rule(code)
    title, default_risk, default_second = defaults
    if rule is not None and not rule.enabled:
        return
    risk = rule.risk_level if rule is not None else default_risk
    second = (
        rule.second_approval_required
        if rule is not None
        else default_second
    )
    payload = dict(metadata or {})
    payload["second_approval_required"] = bool(second)
    payload["rule_title"] = rule.title if rule is not None else title
    findings.append(
        VerificationFinding(
            submission=submission,
            rule=rule,
            run_id=run_id,
            code=code,
            risk_level=risk,
            message=message,
            expected_value=str(expected or ""),
            submitted_value=str(submitted or ""),
            metadata=payload,
            is_current=True,
        )
    )


def _parent_checks(findings, submission, run_id, sire, dam, child_dob):
    if not child_dob:
        return
    for role, parent in (("Sire", sire), ("Dam", dam)):
        if parent is None or not parent.date_of_birth:
            continue
        if parent.date_of_birth >= child_dob:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="pedigree_chronology",
                message=f"{role} is recorded as born on or after the offspring date of birth.",
                expected=f"{role} DOB before {child_dob.isoformat()}",
                submitted=parent.date_of_birth.isoformat(),
                metadata={"parent_id": str(parent.pk), "role": role.lower()},
            )
            continue
        age_days = (child_dob - parent.date_of_birth).days
        if age_days < 365:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="young_parent",
                message=f"{role} would have been under 12 months old at the recorded birth. Review supporting evidence rather than rejecting automatically.",
                expected="Parent at least 12 months before offspring DOB",
                submitted=f"{age_days} days",
                metadata={"parent_id": str(parent.pk), "role": role.lower()},
            )


def _payment_checks(findings, submission, run_id):
    if not (submission.payload or {}).get("_paid_submission"):
        return
    from accounts.models import PaymentSubmissionLink, SubmissionPayment

    link = (
        PaymentSubmissionLink.objects.select_related("payment")
        .filter(submission=submission)
        .first()
    )
    if link is None:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="payment_entitlement",
            message="Paid submission has no server-side payment entitlement link.",
            expected="Valid paid package link",
            submitted="Missing",
        )
        return

    payment = link.payment
    problems = []
    if payment.status != SubmissionPayment.Status.PAID:
        problems.append("payment is not confirmed")
    if payment.user_id != submission.submitted_by_id:
        problems.append("payment belongs to a different member")
    if payment.kennel_id != submission.kennel_id:
        problems.append("payment belongs to a different kennel")
    if link.slot_kind == PaymentSubmissionLink.SlotKind.DOG:
        if payment.package not in {
            SubmissionPayment.Package.SINGLE_DOG,
            SubmissionPayment.Package.MULTI_DOG,
        }:
            problems.append("dog slot is not backed by a dog package")
    elif link.slot_kind in {
        PaymentSubmissionLink.SlotKind.LITTER,
        PaymentSubmissionLink.SlotKind.PUPPY,
    }:
        if payment.package != SubmissionPayment.Package.LITTER:
            problems.append("litter slot is not backed by a litter package")

    if problems:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="payment_entitlement",
            message="; ".join(problems).capitalize() + ".",
            expected="Matching confirmed Paystack entitlement",
            submitted=payment.get_status_display(),
            metadata={"payment_id": str(payment.pk), "slot_kind": link.slot_kind},
        )


def _dog_identity_checks(findings, submission, run_id, payload):
    registration = str(payload.get("registration") or "").strip()
    if registration:
        existing = (
            DogRegistration.objects.select_related("dog")
            .filter(number__iexact=registration)
            .first()
        )
        if existing and existing.dog_id != submission.dog_id:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_registration",
                message=f"Registration number is already attached to {existing.dog.name}.",
                expected="Registration number unique to one canonical dog",
                submitted=registration,
                metadata={"existing_dog_id": str(existing.dog_id)},
            )

    microchip = str(payload.get("microchip_number") or "").strip()
    normalized_chip = "".join(ch for ch in microchip.upper() if ch.isalnum())
    if normalized_chip:
        existing_chip = (
            DogIdentityNumber.objects.select_related("dog")
            .filter(
                kind=DogIdentityNumber.Kind.MICROCHIP,
                normalized_value=normalized_chip,
            )
            .first()
        )
        if existing_chip and existing_chip.dog_id != submission.dog_id:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_microchip",
                message=f"Microchip number is already attached to {existing_chip.dog.name}.",
                expected="Microchip unique to one canonical dog",
                submitted=microchip,
                metadata={"existing_dog_id": str(existing_chip.dog_id)},
            )

    name = str(payload.get("name") or "").strip()
    dob = _date_value(payload.get("date_of_birth"))
    if not name:
        return

    candidates = Dog.objects.filter(normalized_name=normalize_identity_name(name))
    if dob:
        candidates = candidates.filter(date_of_birth=dob)
    if submission.dog_id:
        candidates = candidates.exclude(pk=submission.dog_id)

    sire_id = payload.get("sire_id")
    dam_id = payload.get("dam_id")
    sex = payload.get("sex")
    for candidate in candidates.select_related("sire", "dam")[:5]:
        conflicts = []
        matches = []
        if dob and candidate.date_of_birth == dob:
            matches.append("same DOB")
        if sex and candidate.sex not in {Dog.Sex.UNKNOWN, sex}:
            conflicts.append(f"sex {candidate.get_sex_display()} vs {sex}")
        if sire_id and candidate.sire_id and _id_text(candidate.sire_id) != _id_text(sire_id):
            conflicts.append("different sire")
        elif sire_id and _id_text(candidate.sire_id) == _id_text(sire_id):
            matches.append("same sire")
        if dam_id and candidate.dam_id and _id_text(candidate.dam_id) != _id_text(dam_id):
            conflicts.append("different dam")
        elif dam_id and _id_text(candidate.dam_id) == _id_text(dam_id):
            matches.append("same dam")

        if conflicts:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="existing_identity_conflict",
                message=f"An existing record named {candidate.name} conflicts with submitted identity details: {', '.join(conflicts)}.",
                expected=f"Existing dog {candidate.pk}",
                submitted=f"{name}; {dob or 'DOB unknown'}",
                metadata={"existing_dog_id": str(candidate.pk), "conflicts": conflicts},
            )
        elif dob or matches:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_identity",
                message=f"A likely matching dog already exists: {candidate.name}. Review before creating another canonical record.",
                expected=f"Reuse/merge canonical dog {candidate.pk} if identity is confirmed",
                submitted=f"{name}; {dob or 'DOB unknown'}",
                metadata={"existing_dog_id": str(candidate.pk), "matches": matches},
            )


def _pending_duplicate_checks(findings, submission, run_id, payload):
    if submission.kind != Submission.Kind.DOG:
        return

    name = str(payload.get("name") or "").strip()
    dob = str(payload.get("date_of_birth") or "").strip()
    registration = str(payload.get("registration") or "").strip()
    microchip = "".join(
        ch for ch in str(payload.get("microchip_number") or "").upper()
        if ch.isalnum()
    )

    pending = Submission.objects.filter(
        kind=Submission.Kind.DOG,
        status=Submission.Status.PENDING,
    ).exclude(pk=submission.pk)

    strong_match = None
    if registration:
        strong_match = pending.filter(
            payload__registration__iexact=registration
        ).first()
        if strong_match:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_registration",
                message="The same registration number is present on another pending dog submission.",
                expected=f"Resolve pending submission {strong_match.pk} before publishing another identity",
                submitted=registration,
                metadata={"other_submission_id": str(strong_match.pk)},
            )

    if microchip:
        # Microchip formatting can vary, so normalize the small pending candidate set
        # in Python instead of trusting the raw browser/request formatting.
        for other in pending.exclude(payload__microchip_number="").order_by("-created_at")[:200]:
            other_chip = "".join(
                ch for ch in str((other.payload or {}).get("microchip_number") or "").upper()
                if ch.isalnum()
            )
            if other_chip and other_chip == microchip:
                _add_finding(
                    findings,
                    submission=submission,
                    run_id=run_id,
                    code="duplicate_microchip",
                    message="The same microchip number is present on another pending dog submission.",
                    expected=f"Resolve pending submission {other.pk} before publishing another identity",
                    submitted=str(payload.get("microchip_number") or ""),
                    metadata={"other_submission_id": str(other.pk)},
                )
                break

    if name and dob:
        possible = pending.filter(
            payload__name__iexact=name,
            payload__date_of_birth=dob,
        ).order_by("-created_at").first()
        if possible:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_submission",
                message="Another pending submission has the same dog name and date of birth. Review both identities before publication.",
                expected=f"Compare with pending submission {possible.pk}",
                submitted=f"{name}; {dob}",
                metadata={"other_submission_id": str(possible.pk)},
            )


def _litter_puppy_checks(findings, submission, run_id, payload):
    litter_submission_id = payload.get("litter_submission_id")
    if not litter_submission_id:
        return

    litter_submission = (
        Submission.objects.select_related("litter", "kennel")
        .filter(pk=litter_submission_id, kind=Submission.Kind.LITTER_CREATE)
        .first()
    )
    if litter_submission is None:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="litter_id_conflict",
            message="Puppy points to a litter submission that does not exist.",
            expected=str(litter_submission_id),
            submitted="Missing litter submission",
        )
        return

    expected = litter_submission.payload or {}
    expected_dob = (
        litter_submission.litter.date_of_birth
        if litter_submission.litter_id
        else _date_value(expected.get("date_of_birth"))
    )
    expected_sire = (
        litter_submission.litter.sire_id
        if litter_submission.litter_id
        else expected.get("sire_id")
    )
    expected_dam = (
        litter_submission.litter.dam_id
        if litter_submission.litter_id
        else expected.get("dam_id")
    )
    expected_code = (
        litter_submission.litter.code
        if litter_submission.litter_id
        else str(expected.get("code") or "")
    )

    submitted_dob = _date_value(payload.get("date_of_birth"))
    if expected_dob and submitted_dob and expected_dob != submitted_dob:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="litter_dob_conflict",
            message="Submitted puppy DOB does not match the litter DOB.",
            expected=expected_dob.isoformat(),
            submitted=submitted_dob.isoformat(),
            metadata={"litter_submission_id": str(litter_submission.pk)},
        )
    elif expected_dob and not submitted_dob:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="missing_litter_core_data",
            message="Litter has a DOB but this puppy submission omitted DOB, so litter membership needs review.",
            expected=expected_dob.isoformat(),
            submitted="Not provided",
        )

    if payload.get("sire_id") and expected_sire and _id_text(payload.get("sire_id")) != _id_text(expected_sire):
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="litter_parent_conflict",
            message="Submitted sire does not match the litter sire.",
            expected=_id_text(expected_sire),
            submitted=_id_text(payload.get("sire_id")),
        )
    if payload.get("dam_id") and expected_dam and _id_text(payload.get("dam_id")) != _id_text(expected_dam):
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="litter_parent_conflict",
            message="Submitted dam does not match the litter dam.",
            expected=_id_text(expected_dam),
            submitted=_id_text(payload.get("dam_id")),
        )
    if payload.get("litter_code") and expected_code and payload.get("litter_code") != expected_code:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="litter_id_conflict",
            message="Submitted litter ID does not match the paid litter record.",
            expected=expected_code,
            submitted=payload.get("litter_code"),
        )

    if not expected_dob or not expected_sire or not expected_dam:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="missing_litter_core_data",
            message="The litter is missing one or more core identity facts (DOB, sire or dam). This is not fraud, but evidence should be reviewed.",
            expected="DOB, sire and dam where available",
            submitted=f"DOB={expected_dob or 'missing'}, sire={expected_sire or 'missing'}, dam={expected_dam or 'missing'}",
        )

    declared = expected.get("declared_puppy_count")
    try:
        declared = int(declared) if declared not in (None, "") else None
    except (TypeError, ValueError):
        declared = None
    if declared:
        from accounts.models import PaymentSubmissionLink

        litter_payment = (
            PaymentSubmissionLink.objects.filter(submission=litter_submission)
            .values_list("payment_id", flat=True)
            .first()
        )
        if litter_payment:
            puppy_count = PaymentSubmissionLink.objects.filter(
                payment_id=litter_payment,
                slot_kind=PaymentSubmissionLink.SlotKind.PUPPY,
            ).count()
            if puppy_count > declared:
                _add_finding(
                    findings,
                    submission=submission,
                    run_id=run_id,
                    code="litter_count_exceeded",
                    message="More puppies have been submitted than the litter's declared puppy count.",
                    expected=str(declared),
                    submitted=str(puppy_count),
                    metadata={"litter_submission_id": str(litter_submission.pk)},
                )


def _litter_checks(findings, submission, run_id, payload):
    code = str(payload.get("code") or "").strip()
    sire_id = payload.get("sire_id")
    dam_id = payload.get("dam_id")
    litter_dob = _date_value(payload.get("date_of_birth"))
    try:
        declared_puppy_count = int(payload.get("declared_puppy_count")) if payload.get("declared_puppy_count") not in (None, "") else None
    except (TypeError, ValueError):
        declared_puppy_count = None

    if declared_puppy_count and declared_puppy_count > 20:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="unusually_large_litter",
            message="The declared litter size is unusually large and should be supported by breeding/litter documentation. This is not an automatic rejection.",
            expected="A documented biologically plausible litter size",
            submitted=str(declared_puppy_count),
        )

    if submission.kind == Submission.Kind.LITTER_CREATE:
        if code and Litter.objects.filter(code__iexact=code).exists():
            existing = Litter.objects.filter(code__iexact=code).first()
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_litter",
                message=f"A litter with this ID already exists: {existing.code}.",
                expected=f"Existing litter {existing.pk}",
                submitted=code,
            )

        if sire_id and dam_id and litter_dob:
            duplicate = (
                Litter.objects.filter(
                    kennel_id=submission.kennel_id,
                    sire_id=sire_id,
                    dam_id=dam_id,
                    date_of_birth=litter_dob,
                )
                .first()
            )
            if duplicate:
                _add_finding(
                    findings,
                    submission=submission,
                    run_id=run_id,
                    code="duplicate_litter",
                    message="A litter with the same kennel, parents and DOB already exists.",
                    expected=f"{duplicate.code} ({duplicate.pk})",
                    submitted=code or "No litter code",
                )

    if not sire_id or not dam_id or not litter_dob:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="missing_litter_core_data",
            message="The litter is missing one or more core identity facts (DOB, sire or dam). This is reviewable, not an automatic rejection.",
            expected="DOB, sire and dam where available",
            submitted=f"DOB={litter_dob or 'missing'}, sire={sire_id or 'missing'}, dam={dam_id or 'missing'}",
        )

    sire = Dog.objects.filter(pk=sire_id).first() if sire_id else None
    dam = Dog.objects.filter(pk=dam_id).first() if dam_id else None
    _parent_checks(findings, submission, run_id, sire, dam, litter_dob)

    if submission.kind == Submission.Kind.LITTER_EDIT and submission.litter_id:
        current = submission.litter
        critical = []
        if litter_dob != current.date_of_birth:
            critical.append(("DOB", current.date_of_birth, litter_dob))
        if _id_text(sire_id) != _id_text(current.sire_id):
            critical.append(("sire", current.sire_id, sire_id))
        if _id_text(dam_id) != _id_text(current.dam_id):
            critical.append(("dam", current.dam_id, dam_id))
        if code and code != current.code:
            critical.append(("litter ID", current.code, code))
        if critical and current.is_public:
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="locked_ancestry_change",
                message="This correction changes protected fields on a published litter.",
                expected="; ".join(f"{name}={old}" for name, old, _ in critical),
                submitted="; ".join(f"{name}={new}" for name, _, new in critical),
                metadata={"changes": [(name, _id_text(old), _id_text(new)) for name, old, new in critical]},
            )


def _correction_checks(findings, submission, run_id, payload):
    dog = submission.dog
    if dog is None or not dog.is_public:
        return
    critical = []
    if "date_of_birth" in payload and _date_value(payload.get("date_of_birth")) != dog.date_of_birth:
        critical.append(("DOB", dog.date_of_birth, _date_value(payload.get("date_of_birth"))))
    if "sire_id" in payload and _id_text(payload.get("sire_id")) != _id_text(dog.sire_id):
        critical.append(("sire", dog.sire_id, payload.get("sire_id")))
    if "dam_id" in payload and _id_text(payload.get("dam_id")) != _id_text(dog.dam_id):
        critical.append(("dam", dog.dam_id, payload.get("dam_id")))
    if "litter_id" in payload and _id_text(payload.get("litter_id")) != _id_text(dog.litter_id):
        critical.append(("litter", dog.litter_id, payload.get("litter_id")))
    if "sex" in payload and payload.get("sex") != dog.sex:
        critical.append(("sex", dog.sex, payload.get("sex")))

    current_registration = dog.registrations.filter(authority__isnull=True).first()
    current_registration_value = current_registration.number if current_registration else ""
    if "registration" in payload and str(payload.get("registration") or "").strip() != current_registration_value:
        critical.append(("registration", current_registration_value, str(payload.get("registration") or "").strip()))

    current_microchip = dog.identity_numbers.filter(
        kind=DogIdentityNumber.Kind.MICROCHIP
    ).first()
    current_microchip_value = current_microchip.value if current_microchip else ""
    if "microchip_number" in payload and str(payload.get("microchip_number") or "").strip() != current_microchip_value:
        critical.append(("microchip", current_microchip_value, str(payload.get("microchip_number") or "").strip()))
    if critical:
        _add_finding(
            findings,
            submission=submission,
            run_id=run_id,
            code="locked_ancestry_change",
            message="This correction changes protected ancestry fields on a published dog. Preserve the old values in the audit trail and require high-risk review.",
            expected="; ".join(f"{name}={old}" for name, old, _ in critical),
            submitted="; ".join(f"{name}={new}" for name, _, new in critical),
            metadata={"changes": [(name, _id_text(old), _id_text(new)) for name, old, new in critical]},
        )


def _photo_checks(findings, submission, run_id):
    hashes = list(
        submission.verification_evidence.filter(
            evidence_type=SubmissionEvidence.EvidenceType.PHOTO
        )
        .exclude(sha256="")
        .values_list("sha256", flat=True)
    )
    payload_hash = str((submission.payload or {}).get("sha256") or "").strip()
    if payload_hash:
        hashes.append(payload_hash)

    for digest in set(hashes):
        other_evidence = (
            SubmissionEvidence.objects.select_related("submission")
            .filter(sha256=digest, evidence_type=SubmissionEvidence.EvidenceType.PHOTO)
            .exclude(submission=submission)
            .first()
        )
        existing_image = DogImage.objects.filter(content_sha256=digest).first()
        other_submission = (
            Submission.objects.filter(
                kind=Submission.Kind.IMAGE,
                status=Submission.Status.PENDING,
                payload__sha256=digest,
            )
            .exclude(pk=submission.pk)
            .first()
        )
        if other_evidence or existing_image or other_submission:
            metadata = {}
            if other_evidence:
                metadata["other_submission_id"] = str(other_evidence.submission_id)
            if existing_image:
                metadata["existing_dog_id"] = str(existing_image.dog_id)
                metadata["existing_image_id"] = existing_image.pk
            if other_submission:
                metadata["other_pending_submission_id"] = str(other_submission.pk)
            _add_finding(
                findings,
                submission=submission,
                run_id=run_id,
                code="duplicate_photo",
                message="The same image content already appears in another dog record or pending verification submission. Review context before deciding.",
                expected="Unique identity photo unless reuse is documented",
                submitted=digest,
                metadata=metadata,
            )


def current_findings(submission):
    return submission.verification_findings.filter(is_current=True).select_related("rule")


def verification_snapshot(submission):
    return [
        {
            "code": finding.code,
            "risk": finding.risk_level,
            "message": finding.message,
            "expected": finding.expected_value,
            "submitted": finding.submitted_value,
        }
        for finding in current_findings(submission)
    ]


@transaction.atomic
def verify_submission(submission, *, audit=True):
    submission = Submission.objects.select_for_update().select_related(
        "dog", "litter", "kennel"
    ).get(pk=submission.pk)
    run_id = uuid.uuid4()
    VerificationFinding.objects.filter(
        submission=submission, is_current=True
    ).update(is_current=False)

    findings = []
    payload = submission.payload or {}

    _payment_checks(findings, submission, run_id)

    if submission.kind in {Submission.Kind.DOG, Submission.Kind.CORRECTION}:
        _dog_identity_checks(findings, submission, run_id, payload)
        _pending_duplicate_checks(findings, submission, run_id, payload)
        _litter_puppy_checks(findings, submission, run_id, payload)
        _correction_checks(findings, submission, run_id, payload)

        child_dob = _date_value(payload.get("date_of_birth"))
        sire = Dog.objects.filter(pk=payload.get("sire_id")).first() if payload.get("sire_id") else None
        dam = Dog.objects.filter(pk=payload.get("dam_id")).first() if payload.get("dam_id") else None
        _parent_checks(findings, submission, run_id, sire, dam, child_dob)

    if submission.kind in {Submission.Kind.LITTER_CREATE, Submission.Kind.LITTER_EDIT}:
        _litter_checks(findings, submission, run_id, payload)

    _photo_checks(findings, submission, run_id)

    if findings:
        VerificationFinding.objects.bulk_create(findings)

    risk = SubmissionRiskLevel.GREEN
    for finding in findings:
        if RISK_ORDER[finding.risk_level] > RISK_ORDER[risk]:
            risk = finding.risk_level
    requires_second = any(
        bool(finding.metadata.get("second_approval_required"))
        for finding in findings
    )

    open_evidence = submission.evidence_requests.filter(
        status=EvidenceRequest.Status.OPEN
    ).exists()
    if submission.verification_status == SubmissionVerificationStatus.AWAITING_SECOND and findings:
        verification_status = SubmissionVerificationStatus.AWAITING_SECOND
    elif open_evidence:
        verification_status = SubmissionVerificationStatus.AWAITING_EVIDENCE
    elif findings:
        verification_status = SubmissionVerificationStatus.REVIEW
    else:
        verification_status = SubmissionVerificationStatus.PASS

    submission.risk_level = risk
    submission.requires_second_review = requires_second
    submission.verification_status = verification_status
    submission.verification_checked_at = timezone.now()
    submission.save(
        update_fields=(
            "risk_level",
            "requires_second_review",
            "verification_status",
            "verification_checked_at",
            "updated_at",
        )
    )

    if audit:
        ModerationAudit.objects.create(
            action=ModerationAudit.Action.VERIFICATION_RUN,
            dog=submission.dog,
            kennel=submission.kennel,
            litter=submission.litter,
            submission=submission,
            summary={
                "run_id": str(run_id),
                "risk_level": risk,
                "verification_status": verification_status,
                "findings": verification_snapshot(submission),
            },
            note="Automated server-side verification completed.",
        )

    return list(current_findings(submission))
