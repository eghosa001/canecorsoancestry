import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from registry.management.commands.import_canecorso_archive import (
    DEFAULT_SOURCE_TITLE,
    _text,
)
from registry.management.commands.refresh_canecorso_latest import (
    PROFILE_URL,
    USER_AGENT,
    parse_profile,
)
from registry.models import Dog, DogSource, Kennel


OWNER_URL = urljoin("https://www.canecorsopedigree.com/", "view_owner?ownerid={}")

# Conservative country evidence only. Ambiguous/multi-country registrations are
# deliberately left blank rather than pretending the dog's country is known.
REGISTRY_COUNTRY_RULES = (
    (re.compile(r"^LOF\b|^LOF\d", re.I), "France"),
    (re.compile(r"^NHSB\b|^NHSB\d", re.I), "Netherlands"),
    (re.compile(r"^PKR\b|^PKR[. /-]", re.I), "Poland"),
    (re.compile(r"^MET(?:\.|\s)", re.I), "Hungary"),
    (re.compile(r"^JR\b|^JR\s*\d", re.I), "Serbia"),
    (re.compile(r"^RKF\b|^RKF\s*\d", re.I), "Russia"),
    (re.compile(r"^VDH\b|^VDH[ /-]", re.I), "Germany"),
    (re.compile(r"^UKU\b|^UKU[. /-]", re.I), "Ukraine"),
    (re.compile(r"^SPKP\b|^SPKP[ /-]", re.I), "Slovakia"),
    (re.compile(r"^CMKU\b|^CMKU[ /-]", re.I), "Czech Republic"),
    (re.compile(r"^BCU\b|^BCU[ /-]", re.I), "Belarus"),
    (re.compile(r"^HR\b|^HR\s*\d", re.I), "Croatia"),
    (re.compile(r"^MNE\b|^MNE\s*\d", re.I), "Montenegro"),
    (re.compile(r"^ISBR\b|^ISBR\s*\d", re.I), "Israel"),
    (re.compile(r"^FCA\b|^FCA\s*\d", re.I), "Argentina"),
    (re.compile(r"^SE\d", re.I), "Sweden"),
    (re.compile(r"^NO\d", re.I), "Norway"),
    (re.compile(r"^DK\d", re.I), "Denmark"),
    (re.compile(r"^LV\d", re.I), "Latvia"),
    (re.compile(r"^EST\b|^EST\d", re.I), "Estonia"),
    (re.compile(r"^(?:OHZB|ÖHZB)\b|^(?:OHZB|ÖHZB)\d", re.I), "Austria"),
    (re.compile(r"^(?:LO|LI|ROI)\s*\d", re.I), "Italy"),
)


def countries_from_pedigree(value):
    text = _text(value)
    if not text:
        return set()

    fragments = [part.strip() for part in re.split(r"[;,|]+", text) if part.strip()]
    countries = set()
    recognized = 0
    for fragment in fragments:
        country = ""
        for pattern, candidate in REGISTRY_COUNTRY_RULES:
            if pattern.search(fragment):
                country = candidate
                break
        if country:
            recognized += 1
            countries.add(country)

    # Every registration fragment must be recognized and they must all agree.
    if recognized != len(fragments):
        return set()
    return countries


def infer_country(value):
    countries = countries_from_pedigree(value)
    return next(iter(countries)) if len(countries) == 1 else ""


def explicit_kennel_name(value):
    value = _text(value)
    if not value:
        return ""
    match = re.search(r"\(([^()]{2,180})\)\s*$", value)
    if not match:
        return ""
    kennel = _text(match.group(1))
    return "" if kennel.casefold() in {"none", "unknown", "n/a"} else kennel


def owner_page_kennel(html):
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(
        string=lambda x: re.sub(r"\s+", " ", str(x or "")).strip().rstrip(":")
        == "Kennel Name"
    )
    if node is None:
        return ""

    stop_labels = {"Email address", "Website", "Owner Of", "Breeder Of", "Added by"}
    for element in node.next_elements:
        if element is node:
            continue
        if isinstance(element, str):
            text = re.sub(r"\s+", " ", element).strip()
            if not text:
                continue
            if text.rstrip(":") in stop_labels:
                break
            if text.casefold() not in {"kennel name", "none", "unknown", "n/a"}:
                return text
    return ""


def _unique_kennel_slug(name):
    base = slugify(name)[:185] or "kennel"
    slug = base
    suffix = 2
    while Kennel.objects.filter(slug=slug).exists():
        existing = Kennel.objects.filter(slug=slug).first()
        if existing and existing.name.casefold() == name.casefold():
            return slug
        tail = f"-{suffix}"
        slug = f"{base[:190-len(tail)]}{tail}"
        suffix += 1
    return slug


def _get_or_create_kennel(name):
    kennel = Kennel.objects.filter(name__iexact=name).first()
    if kennel:
        return kennel, False
    return (
        Kennel.objects.create(
            name=name[:180],
            slug=_unique_kennel_slug(name),
            description=(
                "Kennel name sourced from CaneCorsoPedigree breeder metadata. "
                "It is not inferred by splitting the dog's name."
            ),
        ),
        True,
    )


class Command(BaseCommand):
    help = (
        "Backfill conservative country evidence and explicit breeder kennel metadata "
        "for existing CaneCorsoPedigree source records."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=8000)
        parser.add_argument("--delay", type=float, default=0.1)
        parser.add_argument("--timeout", type=float, default=20)
        parser.add_argument("--country-only", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        country_updates = []
        source_updates = []

        archive_sources = (
            DogSource.objects.filter(title=DEFAULT_SOURCE_TITLE)
            .select_related("dog")
            .order_by("id")
        )
        for source in archive_sources.iterator(chunk_size=1000):
            dog = source.dog
            if dog.country.strip():
                continue
            payload = dict(source.raw_payload or {})
            country = infer_country(payload.get("pedigree_number"))
            if not country:
                continue
            dog.country = country
            dog.updated_at = now
            country_updates.append(dog)
            payload["country_evidence"] = {
                "value": country,
                "method": "registration_prefix",
                "confidence": "high",
                "registration": _text(payload.get("pedigree_number")),
            }
            source.raw_payload = payload
            source_updates.append(source)

        if country_updates:
            Dog.objects.bulk_update(
                country_updates, ["country", "updated_at"], batch_size=1000
            )
            DogSource.objects.bulk_update(
                source_updates, ["raw_payload"], batch_size=500
            )

        if options["country_only"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Country backfill complete: {len(country_updates)} dogs updated."
                )
            )
            return

        limit = max(0, options["limit"])
        delay = max(0.0, options["delay"])
        timeout = max(1.0, options["timeout"])
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        owner_kennel_cache = {}

        candidates = (
            DogSource.objects.filter(
                title=DEFAULT_SOURCE_TITLE,
                dog__kennel__isnull=True,
                raw_payload__metadata_checked_at__isnull=True,
            )
            .select_related("dog")
            .order_by("id")
        )
        if limit:
            candidates = candidates[:limit]

        checked = linked = kennels_created = failed = 0
        for source in candidates.iterator(chunk_size=200):
            payload = dict(source.raw_payload or {})
            source_id = _text(payload.get("id"))
            if not source_id:
                payload["metadata_checked_at"] = timezone.now().isoformat()
                source.raw_payload = payload
                source.save(update_fields=["raw_payload"])
                checked += 1
                continue

            try:
                response = session.get(PROFILE_URL.format(source_id), timeout=timeout)
                response.raise_for_status()
                record = parse_profile(source_id, response.text)
            except requests.RequestException:
                failed += 1
                continue

            for field in ("owner", "owner_id", "breeder", "breeder_id"):
                value = _text(record.get(field))
                if value:
                    payload[field] = value

            kennel_name = explicit_kennel_name(record.get("breeder"))
            breeder_id = _text(record.get("breeder_id"))
            if not kennel_name and breeder_id:
                if breeder_id not in owner_kennel_cache:
                    try:
                        owner_response = session.get(
                            OWNER_URL.format(breeder_id), timeout=timeout
                        )
                        owner_response.raise_for_status()
                        owner_kennel_cache[breeder_id] = owner_page_kennel(
                            owner_response.text
                        )
                    except requests.RequestException:
                        owner_kennel_cache[breeder_id] = ""
                kennel_name = owner_kennel_cache[breeder_id]

            if kennel_name and source.dog.kennel_id is None:
                with transaction.atomic():
                    kennel, created = _get_or_create_kennel(kennel_name)
                    if created:
                        kennels_created += 1
                    if source.dog.kennel_id is None:
                        source.dog.kennel = kennel
                        source.dog.save(update_fields=["kennel", "updated_at"])
                        linked += 1
                payload["kennel_evidence"] = {
                    "value": kennel_name,
                    "method": "source_breeder",
                    "confidence": "high",
                    "breeder": _text(record.get("breeder")),
                    "breeder_id": breeder_id,
                }

            payload["metadata_checked_at"] = timezone.now().isoformat()
            source.raw_payload = payload
            source.save(update_fields=["raw_payload"])
            checked += 1
            if delay:
                time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(
                "Metadata backfill complete: "
                f"{len(country_updates)} countries updated; "
                f"{checked} source pages checked; {linked} dogs linked to kennels; "
                f"{kennels_created} kennels created; {failed} fetches failed."
            )
        )
