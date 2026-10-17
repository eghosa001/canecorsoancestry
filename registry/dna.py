"""Validate owner-reported lab breed percentages without inferring pedigree purity."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError


def percentage_text(value):
    return format(value, ".2f").rstrip("0").rstrip(".")


def parse_breed_composition(cane_corso_percentage, other_breeds=""):
    """Return JSON-safe percentages; percentages must total exactly 100."""
    def percent(raw):
        try:
            value = Decimal(str(raw))
        except (ValueError, TypeError, InvalidOperation):
            raise ValidationError("Enter a valid breed percentage.") from None
        if not value.is_finite() or not 0 <= value <= 100 or value != value.quantize(Decimal("0.01")):
            raise ValidationError("Each percentage must be 0–100 with at most two decimal places.")
        return value

    cane = percent(cane_corso_percentage)
    composition = [{"breed": "Cane Corso", "percentage": percentage_text(cane)}]
    total, names = cane, {"cane corso"}
    lines = (other_breeds or "").strip().splitlines()
    if len(lines) > 15 or len(other_breeds or "") > 2000:
        raise ValidationError("Enter no more than 15 other breeds.")
    for line in lines:
        if ":" not in line:
            raise ValidationError("Use 'Breed name: percentage', one other breed per line.")
        name, raw = (item.strip() for item in line.rsplit(":", 1))
        if not name or len(name) > 100 or name.casefold() in names or any(ord(c) < 32 for c in name):
            raise ValidationError("Enter each other breed once with a valid name.")
        amount = percent(raw)
        if amount <= 0:
            raise ValidationError("Other breed percentages must be positive.")
        total += amount
        names.add(name.casefold())
        composition.append({"breed": name, "percentage": percentage_text(amount)})
    if total != Decimal("100"):
        raise ValidationError("Cane Corso and other breed percentages must add up to exactly 100%.")
    return composition
