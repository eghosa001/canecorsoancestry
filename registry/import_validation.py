from collections import defaultdict
from datetime import date


class DatasetValidationError(ValueError):
    pass


def _parse_date(value, source_id, field):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DatasetValidationError(
            f"{source_id} has invalid {field} date: {value!r}"
        ) from exc


def _sex(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"male", "female", "unknown", ""}:
        return normalized or "unknown"
    raise DatasetValidationError(f"Invalid sex value: {value!r}")


def validate_records(records):
    if not isinstance(records, list):
        raise DatasetValidationError("Source JSON must contain a dogs list.")

    by_id = {}
    registrations = {}
    normalized_names = defaultdict(list)
    warnings = []

    for record in records:
        if not isinstance(record, dict):
            raise DatasetValidationError("Every dog record must be an object.")
        source_id = str(record.get("id") or "").strip()
        if not source_id:
            raise DatasetValidationError("Every source dog must have an id.")
        if source_id in by_id:
            raise DatasetValidationError(f"Duplicate source dog id: {source_id}")

        name = " ".join(str(record.get("name") or "").split()).strip()
        if not name:
            raise DatasetValidationError(f"Source dog {source_id} has no name.")

        registration = str(record.get("registration") or "").strip().casefold()
        if registration:
            existing = registrations.get(registration)
            if existing:
                raise DatasetValidationError(
                    f"Registration {record.get('registration')!r} is used by both "
                    f"{existing} and {source_id}."
                )
            registrations[registration] = source_id

        normalized = "".join(ch for ch in name.casefold() if ch.isalnum())
        normalized_names[normalized].append(source_id)

        _sex(record.get("sex"))
        _parse_date(record.get("dateOfBirth"), source_id, "dateOfBirth")
        by_id[source_id] = record

    for source_id, record in by_id.items():
        sire_id = record.get("sireId")
        dam_id = record.get("damId")
        if sire_id and sire_id not in by_id:
            raise DatasetValidationError(
                f"{source_id} references missing sireId: {sire_id}"
            )
        if dam_id and dam_id not in by_id:
            raise DatasetValidationError(
                f"{source_id} references missing damId: {dam_id}"
            )
        if sire_id and dam_id and sire_id == dam_id:
            raise DatasetValidationError(
                f"{source_id} uses the same record as sire and dam."
            )

        child_dob = _parse_date(record.get("dateOfBirth"), source_id, "dateOfBirth")
        if sire_id:
            sire = by_id[sire_id]
            if _sex(sire.get("sex")) == "female":
                raise DatasetValidationError(
                    f"{source_id} references female dog {sire_id} as sire."
                )
            sire_dob = _parse_date(sire.get("dateOfBirth"), sire_id, "dateOfBirth")
            if child_dob and sire_dob and sire_dob >= child_dob:
                raise DatasetValidationError(
                    f"{source_id} has sire {sire_id} born on/after the child."
                )
        if dam_id:
            dam = by_id[dam_id]
            if _sex(dam.get("sex")) == "male":
                raise DatasetValidationError(
                    f"{source_id} references male dog {dam_id} as dam."
                )
            dam_dob = _parse_date(dam.get("dateOfBirth"), dam_id, "dateOfBirth")
            if child_dob and dam_dob and dam_dob >= child_dob:
                raise DatasetValidationError(
                    f"{source_id} has dam {dam_id} born on/after the child."
                )

    visiting = set()
    visited = set()

    def visit(source_id):
        if source_id in visiting:
            raise DatasetValidationError(
                f"Pedigree cycle detected at {source_id}"
            )
        if source_id in visited:
            return
        visiting.add(source_id)
        record = by_id[source_id]
        for field in ("sireId", "damId"):
            parent_id = record.get(field)
            if parent_id:
                visit(parent_id)
        visiting.remove(source_id)
        visited.add(source_id)

    for source_id in by_id:
        visit(source_id)

    for ids in normalized_names.values():
        if len(ids) > 1:
            warnings.append(
                "Possible same-name identities: " + ", ".join(ids)
            )

    unknown_sex = sum(
        1 for record in records if _sex(record.get("sex")) == "unknown"
    )
    if unknown_sex:
        warnings.append(f"{unknown_sex} record(s) have unknown sex.")

    return {
        "by_id": by_id,
        "warnings": warnings,
        "record_count": len(records),
        "registration_count": len(registrations),
    }
