import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from registry.models import Dog, DogSource, Kennel


SOURCE_TITLES = (
    "CaneCorsoPedigree.com archive (2026-09-15)",
    "CaneCorsoPedigree.com live pedigree",
)

# Only high-confidence national stud-book / registry identifiers are used.
# If a pedigree carries recognized identifiers from more than one country,
# no country is assigned automatically.
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
    (re.compile(r"^COR\s*A\b", re.I), "Romania"),
    (re.compile(r"^HR\b|^HR\s*\d", re.I), "Croatia"),
    (re.compile(r"^MNE\b|^MNE\s*\d", re.I), "Montenegro"),
    (re.compile(r"^EKF\b|^EKF[. /-]", re.I), "Estonia"),
    (re.compile(r"^ISBR\b|^ISBR\s*\d", re.I), "Israel"),
    (re.compile(r"^FCPR\b|^FCPR\s*\d", re.I), "Puerto Rico"),
    (re.compile(r"^FCA\b|^FCA\s*\d", re.I), "Argentina"),
    (re.compile(r"^CBKC\b|^CBKC\s*\d", re.I), "Brazil"),
    (re.compile(r"^(?:AKC\b|WS\d)", re.I), "United States"),
    (re.compile(r"^SE\d", re.I), "Sweden"),
    (re.compile(r"^NO\d", re.I), "Norway"),
    (re.compile(r"^DK\d", re.I), "Denmark"),
    (re.compile(r"^LV\d", re.I), "Latvia"),
    (re.compile(r"^EST\b|^EST\d", re.I), "Estonia"),
    (re.compile(r"^(?:OHZB|ÖHZB)\b|^(?:OHZB|ÖHZB)\d", re.I), "Austria"),
    # Italian ENCI legacy/current stud-book identifiers.
    (re.compile(r"^(?:LO|LI|ROI)\s*\d", re.I), "Italy"),
)

CONNECTOR_PREFIXES = (
    "DI", "DE", "DEL", "DEI", "DEGLI", "DELL", "D'", "DA", "DAS", "DOS",
    "DO", "DU", "VON", "VOM", "VAN", "IZ", "Z", "OD", "OF", "DES",
    "LA", "LAS", "LOS", "EL", "LE",
)
KENNEL_MARKERS = {
    "KENNEL", "KENNELS", "CUSTODI", "CORSO", "MOLOSSI", "MOLOSSO",
    "CASA", "HOUSE", "GUARD", "GUARDIAN", "EMPIRE", "PRIDE", "MASTINO",
    "MASTIFF", "MASTINES", "CANIS", "CANE",
}
STOP_AFFIXES = {
    "CANE CORSO",
    "CORSO CANE",
    "CANE CORSO ITALIANO",
    "OF THE",
    "DI CANE",
    "DEL CANE",
}


def countries_from_pedigree(value):
    text = str(value or "").strip()
    if not text:
        return set()
    countries = set()
    for part in re.split(r"[;,|]+", text):
        part = re.sub(r"\s+", " ", part).strip()
        if not part:
            continue
        for pattern, country in REGISTRY_COUNTRY_RULES:
            if pattern.search(part):
                countries.add(country)
                break
    return countries


def infer_country(value):
    countries = countries_from_pedigree(value)
    return next(iter(countries)) if len(countries) == 1 else ""


def _tokens(value):
    return [token for token in re.sub(r"\s+", " ", str(value or "").strip()).upper().split(" ") if token]


def _looks_like_kennel_affix(tokens):
    if len(tokens) < 2:
        return False
    candidate = " ".join(tokens)
    if candidate in STOP_AFFIXES:
        return False
    if any(any(ch.isdigit() for ch in token) for token in tokens):
        return False
    has_connector = any(
        token in CONNECTOR_PREFIXES
        or any(token.startswith(prefix + "'") for prefix in ("D", "DELL", "DELLA", "DEGLI"))
        for token in tokens
    )
    has_marker = any(token.strip(".,'()-") in KENNEL_MARKERS for token in tokens)
    return has_connector or has_marker


def kennel_affix_candidates(name, max_words=5):
    tokens = _tokens(name)
    found = set()
    for size in range(2, min(max_words, len(tokens) - 1) + 1):
        for piece in (tokens[:size], tokens[-size:]):
            if _looks_like_kennel_affix(piece):
                found.add(" ".join(piece))
    return found


def display_kennel_name(value):
    words = []
    for word in value.split():
        words.append(word.title())
    return " ".join(words)


class Command(BaseCommand):
    help = (
        "Backfill source-supported country and conservative kennel metadata for "
        "CaneCorsoPedigree imports without overwriting curated values."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--min-kennel-dogs", type=int, default=8)
        parser.add_argument("--max-affix-words", type=int, default=5)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        min_kennel_dogs = max(5, options["min_kennel_dogs"])
        max_affix_words = max(2, min(6, options["max_affix_words"]))

        rows = list(
            DogSource.objects.filter(title__in=SOURCE_TITLES)
            .select_related("dog")
            .order_by("dog_id", "-created_at")
        )

        # One strongest/current source row per dog.
        sources_by_dog = {}
        for source in rows:
            sources_by_dog.setdefault(source.dog_id, source)

        country_updates = []
        inferred_country_by_dog = {}
        for dog_id, source in sources_by_dog.items():
            dog = source.dog
            if dog.country.strip():
                inferred_country_by_dog[dog_id] = dog.country.strip()
                continue
            payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
            country = infer_country(payload.get("pedigree_number"))
            if not country:
                continue
            dog.country = country
            inferred_country_by_dog[dog_id] = country
            country_updates.append(dog)

        source_dogs = [source.dog for source in sources_by_dog.values() if source.dog.is_public]
        candidate_counts = Counter()
        candidates_by_dog = {}
        for dog in source_dogs:
            candidates = kennel_affix_candidates(dog.name, max_words=max_affix_words)
            candidates_by_dog[dog.id] = candidates
            candidate_counts.update(candidates)

        valid_candidates = {
            candidate
            for candidate, count in candidate_counts.items()
            if count >= min_kennel_dogs
        }

        assignments = {}
        assignment_counts = Counter()
        for dog in source_dogs:
            if dog.kennel_id:
                continue
            matches = candidates_by_dog.get(dog.id, set()) & valid_candidates
            if not matches:
                continue
            # Longest specific affix wins; frequency breaks ties.
            chosen = max(
                matches,
                key=lambda value: (
                    len(value.split()),
                    candidate_counts[value],
                    len(value),
                ),
            )
            assignments[dog.id] = chosen
            assignment_counts[chosen] += 1

        # Discard candidates that only survive because of overlapping broader
        # candidates but receive too few actual longest-match assignments.
        assignment_candidates = {
            candidate
            for candidate, count in assignment_counts.items()
            if count >= min_kennel_dogs
        }
        assignments = {
            dog_id: candidate
            for dog_id, candidate in assignments.items()
            if candidate in assignment_candidates
        }

        preview = sorted(
            ((candidate, sum(1 for value in assignments.values() if value == candidate))
             for candidate in assignment_candidates),
            key=lambda item: (-item[1], item[0]),
        )[:30]
        self.stdout.write(
            f"Country backfill candidates: {len(country_updates)}; "
            f"kennel affixes: {len(assignment_candidates)}; "
            f"dog→kennel assignments: {len(assignments)}"
        )
        for candidate, count in preview:
            self.stdout.write(f"  {candidate}: {count}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete; no rows changed."))
            return

        with transaction.atomic():
            if country_updates:
                Dog.objects.bulk_update(country_updates, ["country"], batch_size=1000)

            existing_by_name = {
                kennel.name.casefold(): kennel
                for kennel in Kennel.objects.all()
            }
            kennel_by_candidate = {}
            used_slugs = set(Kennel.objects.values_list("slug", flat=True))
            for candidate in sorted(assignment_candidates):
                display_name = display_kennel_name(candidate)
                existing = existing_by_name.get(display_name.casefold())
                if existing:
                    kennel_by_candidate[candidate] = existing
                    continue
                base_slug = slugify(display_name)[:185] or "kennel"
                slug = base_slug
                suffix = 2
                while slug in used_slugs:
                    tail = f"-{suffix}"
                    slug = f"{base_slug[:190-len(tail)]}{tail}"
                    suffix += 1
                used_slugs.add(slug)
                kennel = Kennel.objects.create(
                    name=display_name[:180],
                    slug=slug,
                    description=(
                        "Source-derived kennel affix inferred conservatively from "
                        "repeated CaneCorsoPedigree dog names."
                    ),
                )
                existing_by_name[display_name.casefold()] = kennel
                kennel_by_candidate[candidate] = kennel

            dogs_to_link = {
                dog.id: dog
                for dog in Dog.objects.filter(id__in=assignments, kennel__isnull=True)
            }
            for dog_id, candidate in assignments.items():
                dog = dogs_to_link.get(dog_id)
                if dog:
                    dog.kennel = kennel_by_candidate[candidate]
            if dogs_to_link:
                Dog.objects.bulk_update(dogs_to_link.values(), ["kennel"], batch_size=1000)

            # Assign a kennel country only when linked dogs strongly agree.
            kennel_country_votes = defaultdict(Counter)
            linked = Dog.objects.filter(
                kennel__in=kennel_by_candidate.values()
            ).exclude(country="").values_list("kennel_id", "country")
            for kennel_id, country in linked:
                kennel_country_votes[kennel_id][country] += 1

            kennel_country_updates = []
            for kennel in kennel_by_candidate.values():
                if kennel.country.strip():
                    continue
                votes = kennel_country_votes.get(kennel.id)
                if not votes:
                    continue
                country, count = votes.most_common(1)[0]
                total = sum(votes.values())
                if count >= 3 and count / total >= 0.80:
                    kennel.country = country
                    kennel_country_updates.append(kennel)
            if kennel_country_updates:
                Kennel.objects.bulk_update(
                    kennel_country_updates, ["country"], batch_size=500
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete: {len(country_updates)} dog countries; "
                f"{len(assignment_candidates)} kennel affixes; "
                f"{len(dogs_to_link)} dogs linked to kennels."
            )
        )
