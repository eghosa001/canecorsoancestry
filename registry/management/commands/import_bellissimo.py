import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from registry.import_validation import DatasetValidationError, validate_records
from registry.models import (
    Dog,
    DogExternalKey,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    Kennel,
    VerificationState,
)


DEFAULT_SOURCE = Path("data/seeds/bellissimo-dogs.json")
DEFAULT_SOURCE_URL = (
    "https://github.com/eghosa001/bellissimo-geni-cane-corso/"
    "blob/main/data/dogs.json"
)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"Invalid ISO date: {value!r}") from exc


def _validate_graph(records):
    try:
        return validate_records(records)["by_id"]
    except DatasetValidationError as exc:
        raise CommandError(str(exc)) from exc


def _sex(value):
    normalized = str(value or "").strip().lower()
    if normalized == "male":
        return Dog.Sex.MALE
    if normalized == "female":
        return Dog.Sex.FEMALE
    return Dog.Sex.UNKNOWN


def _unique_slug(source_id, namespace):
    base = slugify(source_id) or "dog"
    if not Dog.objects.filter(slug=base).exists():
        return base
    namespaced = slugify(f"{namespace}-{source_id}")
    if not Dog.objects.filter(slug=namespaced).exists():
        return namespaced
    raise CommandError(
        f"Cannot allocate a unique slug for source id {source_id!r}."
    )


class Command(BaseCommand):
    help = "Import the verified Bellissimo Geni public pedigree dataset safely."

    def add_arguments(self, parser):
        parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
        parser.add_argument("--namespace", default="bellissimo-geni")
        parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
        parser.add_argument("--update-existing", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"Source file not found: {source_path}")

        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read source JSON: {exc}") from exc

        records = payload.get("dogs")
        if not isinstance(records, list):
            raise CommandError("Source JSON must contain a dogs list.")

        by_id = _validate_graph(records)
        namespace = options["namespace"].strip()
        if not namespace:
            raise CommandError("Namespace cannot be blank.")

        source_title = "Bellissimo Geni public pedigree dataset"
        schema_version = payload.get("schemaVersion")
        created = 0
        existing = 0
        created_source_ids = set()
        source_to_dog = {}

        with transaction.atomic():
            kennel, _ = Kennel.objects.get_or_create(
                slug="bellissimo-geni",
                defaults={
                    "name": "Bellissimo Geni",
                    "country": "Nigeria",
                    "description": "Imported source kennel for verified Bellissimo Geni records.",
                },
            )

            for source_id, record in by_id.items():
                external = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(namespace=namespace, key=source_id)
                    .first()
                )
                source_kennel = (
                    kennel
                    if record.get("group") in {"current", "past-production"}
                    else None
                )
                values = {
                    "name": str(record["name"]).strip(),
                    "sex": _sex(record.get("sex")),
                    "date_of_birth": _parse_date(record.get("dateOfBirth")),
                    "colour": str(record.get("colour") or "").strip(),
                    "bloodline": str(record.get("bloodline") or "").strip(),
                    "bio": str(record.get("bio") or "").strip(),
                    "kennel": source_kennel,
                    "verification_state": VerificationState.SOURCE_ATTACHED,
                    "is_public": record.get("publishStatus") != "draft",
                }

                if external:
                    dog = external.dog
                    existing += 1
                    if options["update_existing"]:
                        for field, value in values.items():
                            setattr(dog, field, value)
                        dog.save(update_fields=[*values.keys(), "updated_at"])
                else:
                    dog = Dog.objects.create(
                        slug=_unique_slug(source_id, namespace),
                        **values,
                    )
                    DogExternalKey.objects.create(
                        dog=dog,
                        namespace=namespace,
                        key=source_id,
                    )
                    created += 1
                    created_source_ids.add(source_id)

                source_to_dog[source_id] = dog

                registration = str(record.get("registration") or "").strip()
                if registration:
                    existing_registration = DogRegistration.objects.filter(
                        authority__isnull=True,
                        number=registration,
                    ).first()
                    if (
                        existing_registration
                        and existing_registration.dog_id != dog.pk
                    ):
                        raise CommandError(
                            f"Registration {registration!r} belongs to another dog."
                        )
                    DogRegistration.objects.get_or_create(
                        dog=dog,
                        authority=None,
                        number=registration,
                    )

                health = str(record.get("health") or "").strip()
                if health:
                    HealthRecord.objects.get_or_create(
                        dog=dog,
                        test_type="Legacy health summary",
                        result=health[:160],
                        defaults={
                            "verification_state": VerificationState.SOURCE_ATTACHED,
                            "notes": "Imported verbatim from the source pedigree record.",
                        },
                    )

                achievements = str(record.get("achievements") or "").strip()
                if achievements:
                    for title_text in achievements.split("·"):
                        title_text = title_text.strip()
                        if title_text:
                            DogTitle.objects.get_or_create(
                                dog=dog,
                                name=title_text[:160],
                                defaults={"source_text": achievements[:220]},
                            )

                DogSource.objects.update_or_create(
                    dog=dog,
                    title=source_title,
                    defaults={
                        "source_type": DogSource.SourceType.PEDIGREE,
                        "source_url": options["source_url"],
                        "notes": (
                            f"Source id: {source_id}; "
                            f"schema version: {schema_version}"
                        ),
                        "raw_payload": record,
                    },
                )

            for source_id, record in by_id.items():
                if (
                    source_id not in created_source_ids
                    and not options["update_existing"]
                ):
                    continue
                dog = source_to_dog[source_id]
                dog.sire = (
                    source_to_dog.get(record.get("sireId"))
                    if record.get("sireId")
                    else None
                )
                dog.dam = (
                    source_to_dog.get(record.get("damId"))
                    if record.get("damId")
                    else None
                )
                dog.full_clean(exclude=("litter",))
                dog.save(update_fields=("sire", "dam", "updated_at"))

            if options["dry_run"]:
                transaction.set_rollback(True)

        draft_count = sum(
            1 for record in records if record.get("publishStatus") == "draft"
        )
        mode = "Dry run" if options["dry_run"] else "Import complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {created} created, {existing} existing, "
                f"{len(records) - draft_count} public, {draft_count} draft."
            )
        )
