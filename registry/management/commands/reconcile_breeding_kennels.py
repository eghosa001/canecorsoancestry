"""Evidence-first reconciliation of missing *breeding* kennels.

Dry-run by default. Never infer breeder from current owner, member account,
dog-name suffix or an unverified litter kennel. Imported documentary evidence
must explicitly identify breeder kennel, agree across available sources, and
map to exactly one already verified Kennel. No new kennels/users are created.
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from registry.archive_breeder_hints import archive_pattern_hints, match_existing_kennel_name, name_tokens
from registry.models import Dog, DogSource, Kennel, ModerationAudit
from registry.public_freshness import invalidate_public_content
from registry.services import record_audit


SOURCE_TITLE = "CaneCorsoPedigree.com archive (2026-09-15)"
EVIDENCE_NOTE = "Documentary breeder metadata corroborated and applied by guarded reconciliation."
BACKUP_CONFIRMATION = "I_HAVE_VERIFIED_AN_ENCRYPTED_OFFSITE_PRODUCTION_BACKUP"


def _normal(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def explicit_breeding_kennel(breeder_field):
    """Return only a parenthesized breeder kennel explicitly in source metadata.

    The 'owner' field is not a substitute for breeder proof, and even a
    matching suffix in the *dog's name* is never proof of breeding origin.
    """
    text = str(breeder_field or "").strip()
    found = re.search(r"\(([^()]{2,180})\)\s*$", text)
    value = found.group(1).strip() if found else ""
    return "" if _normal(value) in {"none", "unknown", "n/a", "not recorded"} else value


def _kennel_maps(kennels):
    by_name = defaultdict(list)
    candidates = []
    for kennel in kennels:
        label = _normal(kennel.name)
        if label:
            by_name[label].append(kennel)
            # Pattern evidence is NEVER high-confidence enough to auto-link.
            if len(label) >= 5:
                candidates.append((label, kennel))
    return by_name, candidates


def _name_hints(name, names, limit=3):
    """Find full kennel names at name start, middle or end.

    These are PROPOSALS ONLY, not breeder-proof matches. Prefer a longer
    unique complete kennel phrase; multiple labels make a name ambiguous.
    """
    hints = []
    for label, kennel in names:
        placement = match_existing_kennel_name(name, kennel.name)
        if placement:
            hints.append((kennel, placement))
    order = {"suffix": 0, "prefix": 1, "middle": 2}
    hints.sort(key=lambda hit: (
        -len(name_tokens(hit[0].name)),
        order[hit[1]],
        -len(hit[0].name),
        hit[0].name.casefold(),
    ))
    return [kennel for kennel, _ in hints[:limit]]


def assess(dog, sources, by_name, patterns):
    """Return (category, matched_kennel, reason, hints).

    'safe' requires the source explicitly identifying the breeder's kennel,
    matching stored source evidence from the same exact pedigree import,
    a verified unique canonical kennel and no conflicting pedigree evidence.
    Even this evidence is corroborated metadata, not an independent claim
    that an unverified breeder or owner is legitimate.
    """
    proof = set()
    incomplete = set()
    contradictions = False
    for source in sources:
        if source.title != SOURCE_TITLE:
            continue
        payload = source.raw_payload or {}
        if not isinstance(payload, dict):
            continue
        raw_breeder = explicit_breeding_kennel(payload.get("breeder"))
        raw_evidence = payload.get("kennel_evidence") or {}
        if not isinstance(raw_evidence, dict):
            raw_evidence = {}
        ev_name = str(raw_evidence.get("value") or "").strip()
        method = raw_evidence.get("method")
        if raw_breeder:
            incomplete.add(_normal(raw_breeder))
        if ev_name:
            incomplete.add(_normal(ev_name))
        if raw_breeder and ev_name and _normal(raw_breeder) != _normal(ev_name):
            contradictions = True
        if (raw_breeder and ev_name and
                _normal(raw_breeder) == _normal(ev_name) and
                method == "source_breeder" and
                payload.get("breeder_id")):
            proof.add(_normal(raw_breeder))
    hints = _name_hints(dog.name, patterns)
    if dog.litter_id and dog.litter and dog.litter.kennel:
        hints = [dog.litter.kennel] + [
            k for k in hints if k.pk != dog.litter.kennel_id
        ]
        hints = hints[:3]
    if contradictions or len(incomplete) > 1 or len(proof) > 1:
        return ("review", None, "conflicting_breeder_evidence", hints)
    if proof:
        label = next(iter(proof))
        matches = by_name.get(label, ())
        if len(matches) != 1:
            return ("review", None, "unknown_or_ambiguous_registered_kennel", hints)
        kennel = matches[0]
        if not kennel.verified_at:
            return ("review", None, "kennel_identity_not_verified", [kennel]+hints[:2])
        if dog.is_record_locked or dog.visibility_locked_by_superadmin:
            return ("review", None, "super_admin_protected", [kennel]+hints[:2])
        if dog.litter_id and dog.litter and dog.litter.kennel_id and dog.litter.kennel_id != kennel.pk:
            return ("review", None, "documentary_litter_conflict", [kennel]+hints[:2])
        return ("safe", kennel, "explicit_source_breeder_and_verified_kennel", hints)
    if incomplete:
        label = next(iter(incomplete)) if len(incomplete) == 1 else None
        matches = by_name.get(label, ()) if label else ()
        return ("review", None, "incomplete_documentary_breeder_evidence",
                list(matches[:2]) or hints)
    if hints:
        return ("review", None, "name_or_litter_hint_requires_human_proof", hints)
    if archive_pattern_hints(dog.name, limit=1):
        # A recurring phrase in 116,370 source dogs can identify a
        # plausible NEW kennel but is not enough to create a canonical
        # kennel or publish any dog->kennel association.
        return ("review", None, "archive_kennel_name_pattern_needs_verification", [])
    return ("unresolved", None, "no_documented_breeder", [])


def _source_groups():
    groups = defaultdict(list)
    qs = (
        DogSource.objects.filter(dog__kennel__isnull=True)
        .only("dog_id", "title", "raw_payload")
        .order_by("dog_id", "pk")
    )
    for source in qs.iterator(chunk_size=1200):
        groups[source.dog_id].append(source)
    return groups


def _scan(*, max_review_records=2000):
    kennels = list(Kennel.objects.only("pk", "name", "verified_at", "slug"))
    by_name, patterns = _kennel_maps(kennels)
    sources = _source_groups()
    counts = Counter()
    review = []
    safe = []
    qs = (
        Dog.objects.filter(kennel__isnull=True)
        .select_related("litter__kennel")
        .only("pk", "name", "kennel_id", "litter_id", "litter__kennel_id",
              "litter__kennel__name", "is_record_locked",
              "visibility_locked_by_superadmin", "updated_at")
        .order_by("pk")
    )
    for dog in qs.iterator(chunk_size=750):
        category, kennel, reason, hints = assess(
            dog, sources.get(dog.pk, ()), by_name, patterns,
        )
        counts[category] += 1
        counts[reason] += 1
        if category == "safe":
            safe.append((dog.pk, kennel.pk, dog.updated_at))
        elif category == "review" and len(review) < max_review_records:
            review.append({
                "dog_id": str(dog.pk), "dog_name": dog.name,
                "suggested_kennels": [
                    {"id": str(k.pk), "name": k.name} for k in hints
                ],
                "archive_name_hypotheses": archive_pattern_hints(
                    dog.name, limit=3,
                ),
                "reason": reason, "action": "staff_review_only",
            })
    return counts, safe, review


class Command(BaseCommand):
    help = (
        "Inventory every dog missing a verified breeding kennel. "
        "Dry-run defaults to read-only; only verified, exact documentary "
        "breeder evidence may be applied after an offsite backup."
    )

    def add_arguments(self, parser):
        parser.add_argument("--report-path", type=str)
        parser.add_argument("--review-sample-limit", type=int, default=2000)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-safe", type=int)
        parser.add_argument("--max-updates", type=int, default=250)
        parser.add_argument("--backup-confirmation", type=str, default="")

    def handle(self, *args, **options):
        if options["max_updates"] < 0 or options["review_sample_limit"] < 0:
            raise CommandError("Limits must be nonnegative.")
        if options["apply"]:
            if options["backup_confirmation"] != BACKUP_CONFIRMATION:
                raise CommandError("Verify an encrypted offsite backup before applying changes.")
            if options["expected_safe"] is None:
                raise CommandError("Supply --expected-safe from a freshly reviewed dry-run.")
        counts, safe, review = _scan(
            max_review_records=options["review_sample_limit"]
        )
        self.stdout.write("BREEDING_KENNEL_RECONCILIATION=" + json.dumps({
            "missing_kennel_total": sum(counts.get(category, 0) for category in ("safe", "review", "unresolved")),
            "documentary_auto_eligible": counts["safe"],
            "moderator_review_required": counts["review"],
            "no_proven_breeder_keep_blank": counts["unresolved"],
            "review_sample_exported": len(review),
            "review_sample_truncated": counts["review"] > len(review),
            "reasons": {k:v for k,v in sorted(counts.items())
                        if k not in {"safe","review","unresolved"}},
        }, sort_keys=True))
        if options["report_path"]:
            path = Path(options["report_path"])
            path.write_text(json.dumps({
                "summary": {
                    "safe": counts["safe"],
                    "review": counts["review"],
                    "unresolved": counts["unresolved"],
                    **dict(counts),
                },
                "auto_candidates": [
                    {"dog_id": str(did), "breeding_kennel_id": str(kid)}
                    for did, kid, _ in safe
                ],
                "moderator_review_candidates": review,
                "review_truncated": counts["review"] > len(review),
                "note": (
                    "Name and litter matches are hints, NEVER authorization "
                    "to change a canonical dog's breeding kennel."
                ),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        if not options["apply"]:
            self.stdout.write("DRY RUN ONLY: no dog, kennel or moderation records changed.")
            return
        if counts["safe"] != options["expected_safe"]:
            raise CommandError("Safe-candidate count changed; fresh review required.")
        if len(safe) > options["max_updates"]:
            raise CommandError("Safe-candidate batch exceeds approved max-updates; no writes.")
        # The batch is intentionally all-or-nothing. Recheck documentary
        # evidence while holding a row lock before any mutation.
        with transaction.atomic():
            by_name, patterns = _kennel_maps(
                list(Kennel.objects.only("pk", "name", "verified_at", "slug"))
            )
            for dog_id, kennel_id, version in safe:
                # Only lock Dog itself: nullable litter/kennel LEFT JOINs
                # cannot participate in FOR UPDATE on PostgreSQL.
                dog = Dog.objects.select_for_update(
                    of=("self",)
                ).select_related("litter__kennel").get(pk=dog_id)
                if dog.kennel_id is not None or dog.updated_at != version:
                    raise CommandError("A dog was edited after dry-run; nothing applied.")
                current_sources = list(DogSource.objects.filter(dog_id=dog_id))
                category, kennel, reason, _ = assess(
                    dog, current_sources, by_name, patterns
                )
                if category != "safe" or kennel.pk != kennel_id:
                    raise CommandError("Documentary proof changed. No records updated.")
                dog.kennel = kennel
                dog.full_clean()
                dog.save(update_fields=("kennel", "updated_at"))
                record_audit(
                    action=ModerationAudit.Action.RECORD_CHANGED,
                    dog=dog, kennel=kennel, actor=None,
                    summary={
                        "kind": "verified_breeding_kennel_reconciliation",
                        "before": {"kennel_id": None},
                        "after": {"kennel_id": str(kennel.pk)},
                        "basis": reason,
                        "system_approved": True,
                    },
                    note=EVIDENCE_NOTE,
                )
            if safe:
                invalidate_public_content()
        self.stdout.write(f"APPLIED: {len(safe)} independently rechecked links; all changes audited.")
