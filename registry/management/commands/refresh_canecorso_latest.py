import re
import time
from collections import deque
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from registry.management.commands.import_canecorso_archive import (
    DEFAULT_NAMESPACE,
    _date,
    _health,
    _raw_payload,
    _sex,
    _text,
    _titles,
)
from registry.models import (
    Dog,
    DogExternalKey,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    VerificationState,
)


BASE_URL = "https://www.canecorsopedigree.com/"
LATEST_URL = urljoin(BASE_URL, "latest_additions")
PROFILE_URL = urljoin(BASE_URL, "view_dog?id={}")
SOURCE_TITLE = "CaneCorsoPedigree.com live pedigree"
USER_AGENT = (
    "CaneCorsoAncestryResearch/1.0 "
    "(incremental public-pedigree refresh; respectful rate-limited crawler)"
)
LABELS = {
    "Name",
    "Gender",
    "Father",
    "Mother",
    "Dog Parental DNA Confirmed",
    "Picture",
    "Ped#",
    "Titles",
    "Extra titles",
    "DOB",
    "Colour",
    "HD",
    "ED",
    "Heart",
    "Date of death",
    "Other healthscores",
    "Other",
    "DNA PROFILE",
    "DSRA Result",
    "DSRA Result Certified",
    "DVL2 Result",
    "DVL2 Result Certified",
    "Inbred percentage",
    "children",
    "Brothers and sisters",
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dog_id(href):
    if not href:
        return ""
    match = re.search(r"(?:view_pedigree|view_dog)\?id=(\d+)", href)
    return match.group(1) if match else ""


def parse_latest_ids(html):
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    seen = set()

    rows = soup.find_all("tr")
    row_ids = []
    for row in rows:
        source_id = next(
            (
                _dog_id(anchor.get("href"))
                for anchor in row.find_all("a", href=True)
                if _dog_id(anchor.get("href"))
            ),
            "",
        )
        if source_id and source_id not in seen:
            seen.add(source_id)
            row_ids.append(source_id)
    if row_ids:
        return row_ids

    for anchor in soup.find_all("a", href=True):
        source_id = _dog_id(anchor.get("href"))
        if source_id and source_id not in seen:
            seen.add(source_id)
            ids.append(source_id)
    return ids


def _label_value(soup, label):
    node = soup.find(string=lambda x: _clean(x).rstrip(":") == label if x else False)
    if node is None:
        return ""
    values = []
    for element in node.next_elements:
        if element is node:
            continue
        if isinstance(element, str):
            text = _clean(element)
            if not text:
                continue
            if text.rstrip(":") in LABELS:
                break
            if text.lower() not in {"image", "(click to view pedigree)"}:
                values.append(text)
        elif getattr(element, "name", None) == "a":
            text = _clean(element.get_text(" ", strip=True))
            if text and text.lower() != "image":
                values.append(text)
    return values[0] if values else ""


def _parent_id_after_label(soup, label):
    node = soup.find(string=lambda x: _clean(x).rstrip(":") == label if x else False)
    if node is None:
        return ""
    for element in node.next_elements:
        if element is node:
            continue
        if isinstance(element, str):
            text = _clean(element).rstrip(":")
            if text and text not in {label, "Image"} and text in LABELS:
                break
            continue
        if getattr(element, "name", None) == "a":
            source_id = _dog_id(element.get("href"))
            if source_id:
                return source_id
    return ""


def parse_profile(source_id, html):
    soup = BeautifulSoup(html, "html.parser")
    name = _label_value(soup, "Name")
    if name:
        name = re.sub(
            r"\s*\(click to view pedigree\)\s*$", "", name, flags=re.I
        ).strip()
    record = {
        "id": str(source_id),
        "name": name,
        "gender": _label_value(soup, "Gender").lower(),
        "father_id": _parent_id_after_label(soup, "Father"),
        "mother_id": _parent_id_after_label(soup, "Mother"),
        "pedigree_number": _label_value(soup, "Ped#"),
        "titles": _label_value(soup, "Titles"),
        "extra_titles": _label_value(soup, "Extra titles"),
        "dob": _label_value(soup, "DOB"),
        "colour": _label_value(soup, "Colour"),
        "hd": _label_value(soup, "HD"),
        "ed": _label_value(soup, "ED"),
        "heart": _label_value(soup, "Heart"),
        "date_of_death": _label_value(soup, "Date of death"),
        "other_healthscores": _label_value(soup, "Other healthscores"),
        "dna_profile": _label_value(soup, "DNA PROFILE"),
        "dsra_result": _label_value(soup, "DSRA Result"),
        "dsra_certified": _label_value(soup, "DSRA Result Certified"),
        "dvl2_result": _label_value(soup, "DVL2 Result"),
        "dvl2_certified": _label_value(soup, "DVL2 Result Certified"),
        "inbred_percentage": _label_value(soup, "Inbred percentage"),
        "source_url": PROFILE_URL.format(source_id),
    }
    return record


def collect_missing_records(start_ids, fetch_profile, existing_source_ids):
    records = {}
    queued = set()
    queue = deque()

    for source_id in start_ids:
        source_id = str(source_id)
        if source_id not in existing_source_ids and source_id not in queued:
            queue.append(source_id)
            queued.add(source_id)

    while queue:
        source_id = queue.popleft()
        record = fetch_profile(source_id)
        name = _text(record.get("name"))
        if not name:
            continue
        records[source_id] = record
        for field in ("father_id", "mother_id"):
            parent_id = str(record.get(field) or "").strip()
            if (
                parent_id
                and parent_id not in existing_source_ids
                and parent_id not in records
                and parent_id not in queued
            ):
                queue.append(parent_id)
                queued.add(parent_id)

    return records


def collect_missing_profiles(fetch_html, known_ids, limit=250):
    latest_ids = parse_latest_ids(fetch_html(LATEST_URL))[: max(0, limit)]
    return collect_missing_records(
        latest_ids,
        fetch_profile=lambda source_id: parse_profile(
            source_id, fetch_html(PROFILE_URL.format(source_id))
        ),
        existing_source_ids=known_ids,
    )


def _unique_slug(source_id, name):
    base = slugify(f"ccp-{source_id}-{name}")[:225] or f"ccp-{source_id}"
    slug = base
    suffix = 2
    while Dog.objects.filter(slug=slug).exists():
        tail = f"-{suffix}"
        slug = f"{base[:230-len(tail)]}{tail}"
        suffix += 1
    return slug


def import_records(records, publish=True, dry_run=False):
    if not records:
        return {
            "created": 0,
            "existing": 0,
            "registration_matches": 0,
            "skipped_parent_links": 0,
            "preserved_parent_conflicts": 0,
        }

    record_ids = set(records)
    referenced_ids = {
        str(record.get(field) or "").strip()
        for record in records.values()
        for field in ("father_id", "mother_id")
        if str(record.get(field) or "").strip()
    }
    needed_keys = record_ids | referenced_ids
    external_keys = {
        item.key: item
        for item in DogExternalKey.objects.select_related("dog").filter(
            namespace=DEFAULT_NAMESPACE, key__in=needed_keys
        )
    }
    source_to_dog = {
        source_id: item.dog for source_id, item in external_keys.items()
    }
    missing_ids = record_ids - set(external_keys)

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

    created_ids = []
    attached_ids = []
    reused_by_registration = 0

    with transaction.atomic():
        for source_id in sorted(missing_ids, key=int):
            record = records[source_id]
            registration = _text(record.get("pedigree_number"))
            matched_ids = registration_matches.get(registration, set())
            if len(matched_ids) == 1:
                dog = Dog.objects.get(pk=next(iter(matched_ids)))
                reused_by_registration += 1
            else:
                dog = Dog.objects.create(
                    name=_text(record.get("name")),
                    slug=_unique_slug(source_id, record.get("name")),
                    sex=_sex(record.get("gender")),
                    date_of_birth=_date(record.get("dob")),
                    colour=_text(record.get("colour")),
                    verification_state=VerificationState.SOURCE_ATTACHED,
                    is_public=publish,
                )
                created_ids.append(source_id)

            source_to_dog[source_id] = dog
            DogExternalKey.objects.create(
                dog=dog,
                namespace=DEFAULT_NAMESPACE,
                key=source_id,
            )
            attached_ids.append(source_id)

            DogSource.objects.update_or_create(
                dog=dog,
                title=SOURCE_TITLE,
                defaults={
                    "source_type": DogSource.SourceType.PEDIGREE,
                    "source_url": _text(record.get("source_url")),
                    "notes": (
                        f"CaneCorsoPedigree source id {source_id}; "
                        "incremental public pedigree refresh."
                    ),
                    "raw_payload": _raw_payload(record),
                },
            )

            for title in _titles(record):
                DogTitle.objects.get_or_create(
                    dog=dog,
                    name=title[:160],
                    defaults={"source_text": title[:220]},
                )
            for kind, result in _health(record):
                HealthRecord.objects.get_or_create(
                    dog=dog,
                    test_type=kind,
                    result=result[:160],
                    defaults={
                        "verification_state": VerificationState.SOURCE_ATTACHED,
                        "notes": "Imported from CaneCorsoPedigree.com.",
                    },
                )

        skipped_parent_links = 0
        preserved_parent_conflicts = 0
        for source_id in attached_ids:
            dog = source_to_dog[source_id]
            record = records[source_id]
            changed = []
            for field, parent_field, expected_sex in (
                ("sire", "father_id", Dog.Sex.MALE),
                ("dam", "mother_id", Dog.Sex.FEMALE),
            ):
                parent_id = str(record.get(parent_field) or "").strip()
                if not parent_id:
                    continue
                parent = source_to_dog.get(parent_id)
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
                if current_id == parent.pk:
                    continue
                if dog._parent_creates_cycle(parent.pk):
                    skipped_parent_links += 1
                    continue
                setattr(dog, field, parent)
                changed.append(field)
            if changed:
                dog.save(update_fields=[*changed, "updated_at"])

        if dry_run:
            transaction.set_rollback(True)

    return {
        "created": len(created_ids),
        "existing": len(record_ids) - len(missing_ids),
        "registration_matches": reused_by_registration,
        "skipped_parent_links": skipped_parent_links,
        "preserved_parent_conflicts": preserved_parent_conflicts,
    }


def persist_records(records, publish=True, dry_run=False):
    return import_records(records, publish=publish, dry_run=dry_run)


class Command(BaseCommand):
    help = "Refresh CaneCorsoPedigree latest additions incrementally."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=250)
        parser.add_argument("--private", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--delay", type=float, default=0.2)

    def handle(self, *args, **options):
        limit = max(1, min(options["limit"], 250))
        delay = max(0.0, options["delay"])
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

        def fetch_html(url):
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"Could not fetch {url}: {exc}") from exc
            if delay:
                time.sleep(delay)
            return response.text

        known_ids = set(
            DogExternalKey.objects.filter(
                namespace=DEFAULT_NAMESPACE
            ).values_list("key", flat=True)
        )
        records = collect_missing_profiles(fetch_html, known_ids, limit=limit)
        stats = import_records(
            records,
            publish=not options["private"],
            dry_run=options["dry_run"],
        )
        mode = "Dry run" if options["dry_run"] else "Refresh complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {len(records)} missing source records fetched; "
                f"{stats['created']} dogs created; "
                f"{stats['registration_matches']} exact registration matches; "
                f"{stats['skipped_parent_links']} unsafe parent links skipped; "
                f"{stats['preserved_parent_conflicts']} existing parent links preserved."
            )
        )
