import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from registry.models import (
    Dog,
    DogExternalKey,
    DogSource,
    Kennel,
    VerificationState,
)
from registry.services import unique_dog_slug


DEFAULT_SOURCE = Path("data/seeds/bellissimo-puppies.json")
SOURCE_URL = (
    "https://github.com/eghosa001/bellissimo-geni-cane-corso/"
    "blob/main/data/puppies.json"
)
PARENT_NAMESPACE = "bellissimo-geni"
NAMESPACE = "bellissimo-geni-puppies"


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"Invalid puppy date: {value!r}") from exc


def sex_value(value):
    normalized = str(value or "").strip().lower()
    if normalized == "male":
        return Dog.Sex.MALE
    if normalized == "female":
        return Dog.Sex.FEMALE
    if normalized in {"", "unknown"}:
        return Dog.Sex.UNKNOWN
    raise CommandError(f"Invalid puppy sex: {value!r}")


class Command(BaseCommand):
    help = "Import verified Bellissimo Geni puppy pedigree records safely."

    def add_arguments(self, parser):
        parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.exists():
            raise CommandError(f"Source file not found: {source}")

        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read source JSON: {exc}") from exc

        puppies = payload.get("puppies")
        if not isinstance(puppies, list):
            raise CommandError("Source JSON must contain a puppies list.")

        ids = set()
        created = 0
        linked = 0

        with transaction.atomic():
            kennel = Kennel.objects.filter(slug="bellissimo-geni").first()
            if kennel is None:
                raise CommandError(
                    "Bellissimo Geni kennel is missing. Import the canonical dog seed first."
                )

            for record in puppies:
                source_id = str(record.get("id") or "").strip()
                name = " ".join(str(record.get("name") or "").split()).strip()
                if not source_id or not name:
                    raise CommandError("Every puppy record requires id and name.")
                if source_id in ids:
                    raise CommandError(f"Duplicate puppy source id: {source_id}")
                ids.add(source_id)

                sire_key = str(record.get("sireId") or "").strip()
                dam_key = str(record.get("damId") or "").strip()
                sire = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(namespace=PARENT_NAMESPACE, key=sire_key)
                    .first()
                )
                dam = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(namespace=PARENT_NAMESPACE, key=dam_key)
                    .first()
                )
                if sire_key and sire is None:
                    raise CommandError(f"{source_id} references missing sire {sire_key}.")
                if dam_key and dam is None:
                    raise CommandError(f"{source_id} references missing dam {dam_key}.")

                sire_dog = sire.dog if sire else None
                dam_dog = dam.dog if dam else None
                dob = parse_date(record.get("dateOfBirth"))
                sex = sex_value(record.get("sex"))

                if sire_dog and sire_dog.sex == Dog.Sex.FEMALE:
                    raise CommandError(f"{source_id} has a female sire.")
                if dam_dog and dam_dog.sex == Dog.Sex.MALE:
                    raise CommandError(f"{source_id} has a male dam.")
                if sire_dog and sire_dog.date_of_birth and sire_dog.date_of_birth >= dob:
                    raise CommandError(f"{source_id} has an impossible sire birth date.")
                if dam_dog and dam_dog.date_of_birth and dam_dog.date_of_birth >= dob:
                    raise CommandError(f"{source_id} has an impossible dam birth date.")

                external = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(namespace=NAMESPACE, key=source_id)
                    .first()
                )
                dog = external.dog if external else None

                if dog is None:
                    matches = Dog.objects.filter(
                        name__iexact=name,
                        date_of_birth=dob,
                        sire=sire_dog,
                        dam=dam_dog,
                    )[:2]
                    matches = list(matches)
                    if len(matches) > 1:
                        raise CommandError(
                            f"{source_id} matches multiple canonical dogs; review identity first."
                        )
                    dog = matches[0] if matches else None

                if dog is None:
                    dog = Dog(
                        name=name,
                        slug=unique_dog_slug(name),
                        sex=sex,
                        date_of_birth=dob,
                        colour=str(record.get("colour") or "").strip(),
                        country=kennel.country,
                        kennel=kennel,
                        sire=sire_dog,
                        dam=dam_dog,
                        verification_state=VerificationState.SOURCE_ATTACHED,
                        is_public=True,
                    )
                    dog.full_clean()
                    dog.save()
                    created += 1
                else:
                    linked += 1

                DogExternalKey.objects.get_or_create(
                    dog=dog,
                    namespace=NAMESPACE,
                    key=source_id,
                )
                DogSource.objects.update_or_create(
                    dog=dog,
                    title="Bellissimo Geni verified puppy record",
                    defaults={
                        "source_type": DogSource.SourceType.BREEDER,
                        "source_url": SOURCE_URL,
                        "notes": (
                            f"Source id: {source_id}; schema version: "
                            f"{payload.get('schemaVersion')}"
                        ),
                        "raw_payload": record,
                    },
                )

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "Dry run" if options["dry_run"] else "Import complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {len(puppies)} verified puppy records; "
                f"{created} created; {linked} linked to existing canonical dogs."
            )
        )
