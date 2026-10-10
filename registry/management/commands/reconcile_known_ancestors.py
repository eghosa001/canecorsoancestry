"""Reconcile four fully identified archival/Bellissimo pedigree duplicates.

Default is read-only. --apply is deliberately limited to immutable,
registration-backed identity pairs; it never fuzzy-merges dog names.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registry.models import (
    Dog, DogExternalKey, DogRegistration, DogSource, normalize_identity_name,
)
from registry.services import merge_dogs
from pedigrees.services import inbreeding_coefficient


# Bellissimo canonical slug, archive source ID, expected registration digits.
# The source IDs and registrations are corroborated by the two original sources.
IDENTITIES = (
    ("tocco-of-revenge-della-valle-dei-lord", "27801", "12152913"),
    ("karin-della-valle-dei-lord", "50032", "10109455"),
    ("geronimo", "73513", "1419793"),
    ("carlotta", "46027", "1419817"),
)
SOURCE_NAMESPACE = "canecorsopedigree.com"
BELLISSIMO_NAMESPACE = "bellissimo-geni"


def _registration_digits(raw):
    return "".join(ch for ch in str(raw) if ch.isdigit())


def _resolve_pair(canonical_slug, source_id, expected_number):
    canonical = Dog.objects.filter(slug=canonical_slug).first()
    if canonical is None:
        raise CommandError(f"Expected Bellissimo dog not found: {canonical_slug}")
    if not DogExternalKey.objects.filter(
        dog=canonical, namespace=BELLISSIMO_NAMESPACE
    ).exists():
        raise CommandError(f"Missing Bellissimo provenance: {canonical_slug}")
    source_key = DogExternalKey.objects.filter(
        namespace=SOURCE_NAMESPACE, key=source_id
    ).select_related("dog").first()
    if source_key is None:
        raise CommandError(f"Expected archive source ID not found: {source_id}")
    source = source_key.dog
    if source.pk == canonical.pk:
        # Reruns must be idempotent and keep the merged external source ID.
        return canonical, None
    if source.slug != f"ccp-{source_id}-{canonical_slug}":
        raise CommandError(f"Unexpected source dog for {canonical_slug}")
    if (
        normalize_identity_name(canonical.name) != normalize_identity_name(source.name)
        or canonical.sex != source.sex
        or canonical.sex not in (Dog.Sex.MALE, Dog.Sex.FEMALE)
        or not canonical.is_public or not source.is_public
        or canonical.record_locked_at or source.record_locked_at
    ):
        raise CommandError(f"Identity or approval mismatch for {canonical_slug}")
    if (
        canonical.sire_id or canonical.dam_id
        or not source.sire_id or not source.dam_id
    ):
        raise CommandError(f"Conflicting/incomplete parentage for {canonical_slug}")
    if (
        canonical.date_of_birth and source.date_of_birth
        and canonical.date_of_birth != source.date_of_birth
    ):
        raise CommandError(f"Conflicting birth date for {canonical_slug}")
    numbers = DogRegistration.objects.filter(
        dog=canonical
    ).values_list("number", flat=True)
    if expected_number not in {_registration_digits(n) for n in numbers}:
        raise CommandError(f"Canonical registration mismatch: {canonical_slug}")
    source_registrations = [
        str(payload.get("pedigree_number") or "")
        for payload in DogSource.objects.filter(dog=source).values_list(
            "raw_payload", flat=True
        ) if isinstance(payload, dict)
    ]
    if not any(
        expected_number == _registration_digits(part)
        for value in source_registrations
        for part in re.split(r"[;,]", value)
    ):
        raise CommandError(f"Archive registration mismatch: {canonical_slug}")
    return canonical, source


class Command(BaseCommand):
    help = "Preview or safely reconcile four registration-proven duplicate ancestry records."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write reviewed merges.")
        parser.add_argument("--only", choices=[slug for slug, _, _ in IDENTITIES])

    def handle(self, *args, **options):
        pairs = [
            entry for entry in IDENTITIES
            if not options["only"] or entry[0] == options["only"]
        ]
        # Entire operation is atomic: no partial merges if a later pair
        # unexpectedly fails an identity, registration, or pedigree check.
        with transaction.atomic():
            validated = [_resolve_pair(*pair) for pair in pairs]
            for (slug, source_id, _), (canonical, source) in zip(pairs, validated):
                if source is None:
                    self.stdout.write(f"ALREADY RECONCILED {slug}: source {source_id}")
                else:
                    self.stdout.write(f"VERIFIED {slug}: source {source_id}; two linked parents")
            if not options["apply"]:
                self.stdout.write("DRY RUN: no records were modified")
                return

            before = Dog.objects.filter(slug="explosion-custodi-nos").first()
            pre_coi = (
                inbreeding_coefficient(before, public_only=True) * 100
                if before and before.sire_id and before.dam_id else None
            )
            for (slug, _, _), (canonical, source) in zip(pairs, validated):
                if source is not None:
                    history = merge_dogs(canonical, source, performed_by=None)
                    self.stdout.write(
                        f"MERGED {history.retired_slug} into {slug}; "
                        "history and public redirects preserved"
                    )

            after = Dog.objects.filter(slug="explosion-custodi-nos").first()
            post_coi = (
                inbreeding_coefficient(after, public_only=True) * 100
                if after and after.sire_id and after.dam_id else None
            )
            self.stdout.write(
                f"Explosion Custodi Nos published COI: {pre_coi} -> {post_coi}"
            )
            self.stdout.write(self.style.SUCCESS("Verified pedigree reconciliation complete"))
