import re
import unicodedata
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from registry.models import Dog, Kennel, normalize_identity_name


ARCHIVE_NAMESPACE = "canecorsopedigree.com"
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")

CONNECTORS = {
    "DA", "DE", "DEL", "DELL", "DELLA", "DEI", "DEGLI", "DES", "DI",
    "DO", "DOS", "DU", "EL", "LA", "LAS", "LE", "LOS", "OF", "THE",
    "VAN", "VOM", "VON",
}
GENERIC_SINGLE = CONNECTORS | {
    "ARES", "APOLLO", "BELLA", "BLACK", "BOSS", "BRUNO", "CAESAR", "CESAR",
    "CH", "CORSO", "DUKE", "H", "II", "III", "IV", "KING", "LORD", "LUNA",
    "MAXIMO", "MAYA", "NERO", "QUEEN", "ROCKY", "THOR", "ZEUS",
}
GENERIC_PHRASES = {
    ("CANE", "CORSO"),
    ("CORSO", "ITALIANO"),
    ("DEL", "CORSO"),
}


def _tokens(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("’", "'")
    return tuple(part.upper() for part in TOKEN_RE.findall(normalized))


def _candidate_edges(tokens, max_tokens):
    limit = min(max_tokens, len(tokens) - 1)
    for size in range(1, limit + 1):
        yield "prefix", tokens[:size]
        yield "suffix", tokens[-size:]


def _eligible(key, count, standalone_count, *, min_occurrences, min_single_occurrences):
    if not key or any(part.isdigit() for part in key):
        return False
    if key in GENERIC_PHRASES or all(part in CONNECTORS for part in key):
        return False

    if len(key) == 1:
        token = key[0]
        return (
            count >= min_single_occurrences
            and len(token) >= 4
            and token not in GENERIC_SINGLE
            and standalone_count == 0
        )

    return count >= min_occurrences


def _display_name(key):
    words = []
    for index, token in enumerate(key):
        if token in {"II", "III", "IV"}:
            words.append(token)
        elif index and token in CONNECTORS:
            words.append(token.lower())
        else:
            words.append(token.title())
    return " ".join(words)


def _unique_slug(name, used):
    base = slugify(name)[:180] or "inferred-kennel"
    slug = base
    suffix = 2
    while slug in used:
        tail = f"-{suffix}"
        slug = f"{base[:190-len(tail)]}{tail}"
        suffix += 1
    used.add(slug)
    return slug


class Command(BaseCommand):
    help = (
        "Infer kennel names from repeated CaneCorsoPedigree dog-name prefixes and "
        "suffixes without overwriting existing kennel assignments."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--min-occurrences", type=int, default=3)
        parser.add_argument("--min-single-occurrences", type=int, default=12)
        parser.add_argument("--max-tokens", type=int, default=4)
        parser.add_argument("--preview", type=int, default=30)

    def handle(self, *args, **options):
        min_occurrences = max(2, options["min_occurrences"])
        min_single_occurrences = max(min_occurrences, options["min_single_occurrences"])
        max_tokens = max(1, min(6, options["max_tokens"]))

        rows = list(
            Dog.objects.filter(
                is_public=True,
                external_keys__namespace=ARCHIVE_NAMESPACE,
            )
            .values_list("id", "name", "kennel_id")
            .distinct()
        )

        token_rows = []
        edge_counts = Counter()
        standalone = Counter()

        for dog_id, name, kennel_id in rows:
            tokens = _tokens(name)
            if len(tokens) < 2:
                continue
            token_rows.append((dog_id, name, kennel_id, tokens))
            standalone[tokens] += 1
            for side, key in _candidate_edges(tokens, max_tokens):
                edge_counts[(side, key)] += 1

        eligible = {}
        for (side, key), count in edge_counts.items():
            if _eligible(
                key,
                count,
                standalone.get(key, 0),
                min_occurrences=min_occurrences,
                min_single_occurrences=min_single_occurrences,
            ):
                eligible[(side, key)] = count

        existing_kennels = list(Kennel.objects.all())
        existing_by_identity = {
            normalize_identity_name(kennel.name): kennel for kennel in existing_kennels
        }

        assignments = defaultdict(list)
        metadata = {}

        for dog_id, name, kennel_id, tokens in token_rows:
            if kennel_id:
                continue

            matches = []
            for side, key in _candidate_edges(tokens, max_tokens):
                count = eligible.get((side, key))
                if not count:
                    continue
                display = _display_name(key)
                identity = normalize_identity_name(display)
                existing_bonus = 1 if identity in existing_by_identity else 0
                score = (existing_bonus, len(key), count)
                matches.append((score, side, key, display, count))

            if not matches:
                continue

            _, side, key, display, evidence_count = max(matches, key=lambda item: item[0])
            identity = normalize_identity_name(display)
            assignments[identity].append(dog_id)
            metadata.setdefault(
                identity,
                {
                    "display": display,
                    "side": side,
                    "evidence_count": evidence_count,
                    "tokens": len(key),
                },
            )

        ranked = sorted(
            assignments.items(),
            key=lambda item: (-len(item[1]), metadata[item[0]]["display"].casefold()),
        )

        self.stdout.write(
            f"Archive-linked public dogs analysed: {len(rows)}; "
            f"inferred kennel groups: {len(ranked)}; "
            f"unassigned dogs matched: {sum(len(ids) for _, ids in ranked)}."
        )
        for identity, dog_ids in ranked[: options["preview"]]:
            info = metadata[identity]
            self.stdout.write(
                f"{info['display']}: {len(dog_ids)} dogs "
                f"({info['side']}, {info['tokens']} tokens, "
                f"{info['evidence_count']} repeated-edge records)"
            )

        if not options["apply"]:
            self.stdout.write("Dry analysis only. Re-run with --apply to persist assignments.")
            return

        created = 0
        assigned = 0
        used_slugs = set(Kennel.objects.values_list("slug", flat=True))

        with transaction.atomic():
            for identity, dog_ids in ranked:
                info = metadata[identity]
                kennel = existing_by_identity.get(identity)
                if kennel is None:
                    kennel = Kennel.objects.create(
                        name=info["display"],
                        slug=_unique_slug(info["display"], used_slugs),
                        description=(
                            "Inferred from repeated CaneCorsoPedigree archive dog-name "
                            f"{info['side']} patterns across {info['evidence_count']} records. "
                            "This inferred attribution can be refined by verified kennel evidence."
                        ),
                    )
                    existing_by_identity[identity] = kennel
                    created += 1

                assigned += Dog.objects.filter(
                    pk__in=dog_ids,
                    kennel__isnull=True,
                ).update(kennel=kennel)

        self.stdout.write(
            self.style.SUCCESS(
                f"Kennel inference applied: {created} kennels created; "
                f"{assigned} previously unassigned dogs linked."
            )
        )
