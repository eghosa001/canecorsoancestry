import csv
import re
import sys
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from registry.models import (
    Dog,
    DogAlias,
    DogExternalKey,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    VerificationState,
    normalize_identity_name,
)


DEFAULT_NAMESPACE = "canecorsopedigree.com"
DEFAULT_SOURCE_TITLE = "CaneCorsoPedigree.com archive (2026-09-15)"
UNKNOWN_VALUES = {"", "unknown", "nan", "none", "null", "yyyy/mm/dd"}


def _text(value):
    value = str(value or "").strip()
    return "" if value.casefold() in UNKNOWN_VALUES else value


def _source_id(value):
    try:
        return str(int(float(str(value).strip())))
    except (TypeError, ValueError):
        return ""


def _parent_id(value):
    source_id = _source_id(value)
    return source_id if source_id and source_id != "0" else ""


def _year(value):
    match = re.match(r"^(\d{4})", str(value or "").strip())
    if not match:
        return None
    year = int(match.group(1))
    return year if 1800 <= year <= date.today().year else None


def _date(value):
    value = _text(value)
    if not value:
        return None
    for separator in ("/", "-"):
        parts = value.split(separator)
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            continue
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None
    return None


def _sex(value):
    value = _text(value).casefold()
    if value == "male":
        return Dog.Sex.MALE
    if value == "female":
        return Dog.Sex.FEMALE
    return Dog.Sex.UNKNOWN


def _titles(record):
    values = []
    for field in ("titles", "extra_titles"):
        raw = _text(record.get(field))
        if not raw:
            continue
        values.extend(part.strip() for part in re.split(r"[;•\n]+", raw) if part.strip())
    return list(dict.fromkeys(values))


def _health(record):
    pairs = (
        ("HD", record.get("hd")),
        ("ED", record.get("ed")),
        ("Heart", record.get("heart")),
        ("DSRA", record.get("dsra_result")),
        ("DVL2", record.get("dvl2_result")),
        ("DNA profile", record.get("dna_profile")),
        ("Other health", record.get("other_healthscores")),
    )
    return [(kind, _text(value)) for kind, value in pairs if _text(value)]


def _raw_payload(record):
    fields = (
        "id",
        "name",
        "gender",
        "father_name",
        "father_id",
        "mother_name",
        "mother_id",
        "parental_dna_confirmed",
        "pedigree_number",
        "titles",
        "extra_titles",
        "dob",
        "colour",
        "hd",
        "ed",
        "heart",
        "date_of_death",
        "other_healthscores",
        "dna_profile",
        "dsra_result",
        "dsra_certified",
        "dvl2_result",
        "dvl2_certified",
        "inbred_percentage",
        "source_url",
        "image_url",
        "scraped_at",
        "content_sha256",
    )
    return {field: _text(record.get(field)) for field in fields if _text(record.get(field))}


def _cycle_exists(records):
    sys.setrecursionlimit(max(10000, len(records) * 2))
    state = {}

    def visit(source_id):
        status = state.get(source_id, 0)
        if status == 1:
            return True
        if status == 2:
            return False
        state[source_id] = 1
        record = records[source_id]
        for field in ("father_id", "mother_id"):
            parent = _parent_id(record.get(field))
            if not parent or parent == source_id or parent not in records:
                continue
            if visit(parent):
                return True
        state[source_id] = 2
        return False

    return any(visit(source_id) for source_id in records if state.get(source_id, 0) == 0)


class Command(BaseCommand):
    help = "Import the 2020-present CaneCorsoPedigree archive plus required ancestors."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--start-year", type=int, default=2020)
        parser.add_argument("--end-year", type=int, default=date.today().year)
        parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.exists():
            raise CommandError(f"Source CSV not found: {source}")

        start_year = options["start_year"]
        end_year = options["end_year"]
        if start_year > end_year:
            raise CommandError("--start-year must not be after --end-year")

        all_records = {}
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                source_id = _source_id(record.get("id"))
                name = _text(record.get("name"))
                if source_id and name:
                    record["id"] = source_id
                    all_records[source_id] = record

        recent_ids = {
            source_id
            for source_id, record in all_records.items()
            if (year := _year(record.get("dob"))) is not None
            and start_year <= year <= end_year
        }
        selected_ids = set(recent_ids)
        frontier = set(recent_ids)
        while frontier:
            next_frontier = set()
            for source_id in frontier:
                record = all_records[source_id]
                for field in ("father_id", "mother_id"):
                    parent = _parent_id(record.get(field))
                    if parent and parent in all_records and parent not in selected_ids:
                        selected_ids.add(parent)
                        next_frontier.add(parent)
            frontier = next_frontier

        records = {source_id: all_records[source_id] for source_id in selected_ids}
        if _cycle_exists(records):
            raise CommandError("Pedigree cycle detected in selected source records.")

        namespace = options["namespace"].strip()
        if not namespace:
            raise CommandError("Namespace cannot be blank.")

        existing_keys = {
            key.key: key
            for key in DogExternalKey.objects.select_related("dog").filter(
                namespace=namespace, key__in=selected_ids
            )
        }
        source_to_dog = {key: external.dog for key, external in existing_keys.items()}

        missing_ids = selected_ids - set(existing_keys)
        registrations = {
            _text(records[source_id].get("pedigree_number"))
            for source_id in missing_ids
            if _text(records[source_id].get("pedigree_number"))
        }
        registration_matches = {}
        if registrations:
            for number, dog_id in DogRegistration.objects.filter(
                number__in=registrations
            ).values_list("number", "dog_id"):
                registration_matches.setdefault(number, set()).add(dog_id)

        registration_dog_ids = {
            dog_id for dog_ids in registration_matches.values() for dog_id in dog_ids
        }
        registration_identity_names = {}
        if registration_dog_ids:
            for dog in Dog.objects.filter(pk__in=registration_dog_ids).prefetch_related("aliases"):
                registration_identity_names[dog.pk] = {
                    normalize_identity_name(dog.name),
                    *(
                        normalize_identity_name(alias.name)
                        for alias in dog.aliases.all()
                    ),
                }

        created_dogs = []
        newly_attached_ids = []
        reused_by_registration = 0
        registration_identity_conflicts = 0
        existing_slugs = set(
            Dog.objects.filter(slug__startswith="ccp-").values_list("slug", flat=True)
        )

        for source_id in sorted(missing_ids, key=int):
            record = records[source_id]
            pedigree_number = _text(record.get("pedigree_number"))
            matched_ids = registration_matches.get(pedigree_number, set())
            if len(matched_ids) == 1:
                matched_id = next(iter(matched_ids))
                source_identity = normalize_identity_name(record["name"])
                known_identities = registration_identity_names.get(matched_id, set())
                if source_identity in known_identities:
                    dog = Dog.objects.get(pk=matched_id)
                    source_to_dog[source_id] = dog
                    newly_attached_ids.append(source_id)
                    reused_by_registration += 1
                    continue
                registration_identity_conflicts += 1

            base = slugify(f"ccp-{source_id}-{record['name']}")[:225] or f"ccp-{source_id}"
            slug = base
            suffix = 2
            while slug in existing_slugs:
                tail = f"-{suffix}"
                slug = f"{base[:230-len(tail)]}{tail}"
                suffix += 1
            existing_slugs.add(slug)
            dog = Dog(
                name=record["name"].strip(),
                slug=slug,
                sex=_sex(record.get("gender")),
                date_of_birth=_date(record.get("dob")),
                colour=_text(record.get("colour")),
                verification_state=VerificationState.SOURCE_ATTACHED,
                is_public=options["publish"],
            )
            created_dogs.append((source_id, dog))
            source_to_dog[source_id] = dog
            newly_attached_ids.append(source_id)

        published_existing = 0
        with transaction.atomic():
            if options["publish"] and existing_keys:
                source_created_ids = [
                    external.dog_id
                    for external in existing_keys.values()
                    if external.dog.slug.startswith("ccp-") and not external.dog.is_public
                ]
                if source_created_ids:
                    published_existing = Dog.objects.filter(
                        pk__in=source_created_ids,
                        slug__startswith="ccp-",
                        is_public=False,
                    ).update(is_public=True)

            Dog.objects.bulk_create(
                [dog for _, dog in created_dogs],
                batch_size=1000,
            )

            DogExternalKey.objects.bulk_create(
                [
                    DogExternalKey(
                        dog=source_to_dog[source_id],
                        namespace=namespace,
                        key=source_id,
                    )
                    for source_id in newly_attached_ids
                ],
                batch_size=1000,
            )

            existing_source_dogs = set(
                DogSource.objects.filter(
                    dog_id__in=[dog.pk for dog in source_to_dog.values()],
                    title=DEFAULT_SOURCE_TITLE,
                ).values_list("dog_id", flat=True)
            )
            DogSource.objects.bulk_create(
                [
                    DogSource(
                        dog=dog,
                        source_type=DogSource.SourceType.PEDIGREE,
                        title=DEFAULT_SOURCE_TITLE,
                        source_url=_text(records[source_id].get("source_url")),
                        notes=(
                            f"CaneCorsoPedigree source id {source_id}; "
                            "archived 2026-09-15. Images are not republished by this import."
                        ),
                        raw_payload=_raw_payload(records[source_id]),
                    )
                    for source_id, dog in source_to_dog.items()
                    if dog.pk not in existing_source_dogs
                ],
                batch_size=500,
            )

            title_rows = []
            health_rows = []
            for source_id in newly_attached_ids:
                dog = source_to_dog[source_id]
                record = records[source_id]
                for title in _titles(record):
                    title_rows.append(
                        DogTitle(dog=dog, name=title[:160], source_text=title[:220])
                    )
                for kind, result in _health(record):
                    health_rows.append(
                        HealthRecord(
                            dog=dog,
                            test_type=kind,
                            result=result[:160],
                            verification_state=VerificationState.SOURCE_ATTACHED,
                            notes="Imported from the archived source record.",
                        )
                    )
            DogTitle.objects.bulk_create(title_rows, batch_size=1000, ignore_conflicts=True)
            HealthRecord.objects.bulk_create(health_rows, batch_size=1000)

            parent_updates = []
            skipped_parent_links = 0
            preserved_parent_conflicts = 0
            for source_id, dog in source_to_dog.items():
                record = records[source_id]
                changed = False
                for field, parent_field, expected_sex in (
                    ("sire", "father_id", Dog.Sex.MALE),
                    ("dam", "mother_id", Dog.Sex.FEMALE),
                ):
                    parent_source_id = _parent_id(record.get(parent_field))
                    if not parent_source_id:
                        continue
                    parent = source_to_dog.get(parent_source_id)
                    if parent is None or parent.pk == dog.pk:
                        skipped_parent_links += 1
                        continue
                    if parent.sex not in (expected_sex, Dog.Sex.UNKNOWN):
                        skipped_parent_links += 1
                        continue
                    if (
                        dog.date_of_birth
                        and parent.date_of_birth
                        and parent.date_of_birth >= dog.date_of_birth
                    ):
                        skipped_parent_links += 1
                        continue

                    current_id = getattr(dog, f"{field}_id")
                    if current_id and current_id != parent.pk:
                        preserved_parent_conflicts += 1
                        continue
                    if current_id != parent.pk:
                        setattr(dog, field, parent)
                        changed = True
                if changed:
                    parent_updates.append(dog)

            Dog.objects.bulk_update(
                parent_updates,
                ["sire", "dam", "updated_at"],
                batch_size=1000,
            )

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "Dry run" if options["dry_run"] else "Import complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {len(recent_ids)} dogs born {start_year}-{end_year}; "
                f"{len(records)} records including {len(records)-len(recent_ids)} ancestors; "
                f"{len(created_dogs)} created; {len(existing_keys)} already linked; "
                f"{published_existing} existing source-created dogs published; "
                f"{reused_by_registration} matched by exact registration and identity; "
                f"{registration_identity_conflicts} registration identity conflicts kept separate; "
                f"{skipped_parent_links} unsafe parent links skipped; "
                f"{preserved_parent_conflicts} existing parent links preserved."
            )
        )
