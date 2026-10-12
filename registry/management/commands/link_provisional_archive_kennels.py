"""Safely create provisional kennel profiles and LINK EXISTING dogs for research.

Never create dogs or assign user/kennel ownership. Research FK differs from
canonical Dog.kennel, so name matching cannot masquerade as verified breeder
origin. Both dog and kennel pages link to each other and show unverified tags.

Only apply strong full-name phrases observed repeatedly in the ORIGINAL
116,370 pedigree names and family patterns, and only when the existing
canonical dog has an exact original CaneCorsoPedigree external ID.
"""
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from registry.archive_breeder_hints import (
    archive_name_clusters, archive_pattern_hints, name_tokens,
)
from registry.models import Dog, DogExternalKey, Kennel, ModerationAudit
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit


# Exclude generic/breed fragments, short ambiguous words and weakly
# supported clusters. This is a hypothesis (NOT proven breeder ownership).
BAD_PHRASES = {"cane corso", "del corso", "corso", "dog", "kennel"}
SOURCE_NAMESPACE = "canecorsopedigree.com"
MAX_NEW_LINKS = 4000
CONFIRM = "LINK_EXISTING_DOGS_AS_EXPLICITLY_UNVERIFIED_RESEARCH_ONLY"


def _eligible():
    groups = {}
    for group in archive_name_clusters():
        phrase = group["name"]
        tokens = name_tokens(phrase)
        normalized = " ".join(tokens)
        if (
            normalized in BAD_PHRASES
            or len(phrase.strip()) < 5
            or (len(tokens) == 1 and len(tokens[0]) < 6)
            or group["matches"] < 8
            or group["family"] < 4
            or group["exact"] < 8
        ):
            continue
        groups[tokens] = group
    return groups


@dataclass
class Link:
    dog_id: uuid.UUID
    name: str
    label: str
    source_key: str
    evidence: dict
    updated_at: object


def find_candidates():
    """Find strong unambiguous archive-backed name links, with NO writes."""
    groups = _eligible()
    possible = defaultdict(list)
    for key in DogExternalKey.objects.filter(
        namespace=SOURCE_NAMESPACE,
        dog__kennel__isnull=True,
        dog__inferred_kennel__isnull=True,
        dog__is_record_locked=False,
        dog__visibility_locked_by_superadmin=False,
    ).values_list("dog_id", "key").iterator(chunk_size=4000):
        dog_id, source_key = key
        if source_key.isdecimal():
            possible[dog_id].append(source_key)
    matched = []
    reasons = Counter()
    for dog in Dog.objects.filter(
        pk__in=possible,
        kennel__isnull=True,
        inferred_kennel__isnull=True,
        is_record_locked=False,
        visibility_locked_by_superadmin=False,
    ).only("pk", "name", "updated_at").iterator(chunk_size=2000):
        hints = archive_pattern_hints(dog.name, limit=30)
        plausible = {}
        for hint in hints:
            label = tuple(name_tokens(hint["label"]))
            group = groups.get(label)
            if group is not None:
                plausible[label] = (hint, group)
        if not plausible:
            reasons["no_reliable_affix"] += 1
            continue
        if len(plausible) != 1:
            reasons["ambiguous_name_affixes"] += 1
            continue
        hint, group = next(iter(plausible.values()))
        evidence = {
            "origin": "original_pedigree_archive_exact_id",
            "method": "recurring_dog_name_affix_and_family_pattern",
            "verification": "unverified_research_hypothesis",
            "position": hint["position"],
            "phrase": group["name"],
            "matching_archive_source_ids": group["exact"],
            "repeated_family_name_support": group["family"],
        }
        matched.append(Link(
            dog_id=dog.pk, name=dog.name, label=group["name"],
            source_key=min(possible[dog.pk], key=int),
            evidence=evidence, updated_at=dog.updated_at,
        ))
    return matched, reasons


def kennel_map_for_labels(labels):
    """Reuse unique existing kennels; never silently overwrite another name."""
    from registry.models import normalize_identity_name
    by_identity = defaultdict(list)
    for kennel in Kennel.objects.all().only(
        "id", "name", "slug", "is_public", "verified_at",
        "is_archive_hypothesis", "publication_locked_by_superadmin",
    ):
        by_identity[normalize_identity_name(kennel.name)].append(kennel)
    usable, to_create, rejected = {}, {}, {}
    for label in labels:
        key = normalize_identity_name(label)
        matching = by_identity.get(key, [])
        if len(matching) > 1:
            rejected[label] = "ambiguous_duplicate_kennel_names"
        elif matching:
            kennel = matching[0]
            if not kennel.is_public or kennel.publication_locked_by_superadmin:
                rejected[label] = "existing_kennel_not_public_or_locked"
            else:
                usable[label] = kennel
        elif key and len(key) >= 5:
            to_create[label] = label
        else:
            rejected[label] = "invalid_or_generic_name"
    return usable, to_create, rejected


class Command(BaseCommand):
    help = (
        "Propose new unverified historical kennel profiles and real crosslinks "
        "to existing dogs only. Dry-run by default; never alter Dog.kennel."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-links", type=int)
        parser.add_argument("--expected-new-kennels", type=int)
        parser.add_argument("--backup-confirmation", default="")
        parser.add_argument("--max-links", type=int, default=MAX_NEW_LINKS)

    def handle(self, *args, **options):
        if options["max_links"] < 0 or options["max_links"] > MAX_NEW_LINKS:
            raise CommandError("Invalid max link limit")
        if options["apply"] and (
            options["backup_confirmation"] != CONFIRM
            or options["expected_links"] is None
            or options["expected_new_kennels"] is None
        ):
            raise CommandError(
                "A fresh exact-count dry run, independent backup verification "
                "and explicit unverified-research confirmation are required."
            )
        candidates, reasons = find_candidates()
        reusable, new, rejected = kennel_map_for_labels(
            {candidate.label for candidate in candidates}
        )
        plan = [c for c in candidates if c.label not in rejected]
        prospective_new = {c.label for c in plan if c.label in new}
        stats = {
            "existing_dogs_with_new_research_links": len(plan),
            "new_unverified_kennel_profiles": len(prospective_new),
            "existing_kennels_reused": len(
                {c.label for c in plan if c.label in reusable}
            ),
            "skipped_unverified_or_ambiguous": dict(reasons),
            "skipped_unavailable_kennels": len(candidates) - len(plan),
            "dry_run": not options["apply"],
            "no_new_dogs": True,
            "canonical_breeding_kennels_changed": 0,
        }
        self.stdout.write(
            "PROVISIONAL_BREEDER_KENNEL_LINK_PLAN=" +
            json.dumps(stats, sort_keys=True)
        )
        if not options["apply"]:
            self.stdout.write("DRY RUN ONLY: no kennel or dog modified.")
            return
        if (len(plan) != options["expected_links"]
                or len(prospective_new) != options["expected_new_kennels"]
                or len(plan) > options["max_links"]):
            raise CommandError("Candidate counts changed, no records written.")
        from registry.models import normalize_identity_name
        with transaction.atomic():
            # Freshly recheck label identities before creating any public
            # records; no duplicate kennels and no owner memberships.
            current_map, create, bad = kennel_map_for_labels(
                {c.label for c in plan}
            )
            if bad or {x for x in plan if x.label in create} and (
                set(create) != prospective_new
            ):
                raise CommandError("Kennel roster changed. No records written.")
            used_slugs = set(Kennel.objects.values_list("slug", flat=True))
            for label in sorted(prospective_new):
                stem = slugify(label)[:155] or "archived-kennel"
                slug = stem
                if slug in used_slugs:
                    slug = (stem[:150] + "-archive")
                    n = 2
                    while slug in used_slugs:
                        slug = stem[:144] + f"-archive-{n}"
                        n += 1
                used_slugs.add(slug)
                current_map[label] = Kennel.objects.create(
                    name=label,
                    slug=slug,
                    is_public=True,
                    is_archive_hypothesis=True,
                    description=(
                        "Unverified historical kennel-name hypothesis "
                        "from CaneCorsoPedigree dog names and family patterns. "
                        "The breeder's identity and ownership have NOT been "
                        "independently confirmed."
                    ),
                    verified_at=None,
                )
            for candidate in plan:
                dog = Dog.objects.select_for_update(
                    of=("self",)
                ).get(pk=candidate.dog_id)
                if (
                    dog.kennel_id is not None or
                    dog.inferred_kennel_id is not None or
                    dog.updated_at != candidate.updated_at or
                    dog.visibility_locked_by_superadmin or
                    dog.is_record_locked
                ):
                    raise CommandError(
                        "A candidate dog was edited/locked; entire batch rolled back."
                    )
                kennel = current_map[candidate.label]
                dog.inferred_kennel = kennel
                dog.inferred_kennel_evidence = candidate.evidence
                dog.save(update_fields=(
                    "inferred_kennel", "inferred_kennel_evidence", "updated_at"
                ))
                record_audit(
                    action=ModerationAudit.Action.RECORD_CHANGED,
                    dog=dog, kennel=kennel,
                    summary={
                        "kind": "unverified_archive_breeder_name_link",
                        "before": {"inferred_kennel_id": None},
                        "after": {"inferred_kennel_id": str(kennel.pk)},
                        "source_identity_confirmed": True,
                        "breeder_identity_confirmed": False,
                        "name_affix": candidate.label,
                    },
                    note=(
                        "Reversible archival name-pattern research link ONLY; "
                        "does not change canonical breeding kennel or dog owner."
                    ),
                )
            if plan:
                invalidate_public_content()
        self.stdout.write(
            f"APPLIED {len(plan)} provisional existing-dog links; "
            f"created {len(prospective_new)} unverified kennel profiles; "
            "new dogs: 0; canonical origins changed: 0."
        )
