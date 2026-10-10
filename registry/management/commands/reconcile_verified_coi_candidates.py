"""Reconcile a tightly reviewed set of canonical/archive pedigree identities.

Default is strictly read-only. --apply performs one atomic transaction only
if *every* currently present identity passes two-source registration, name,
sex, visibility, birth-date, parentage and merge safety checks.

This is an allowlist, not a fuzzy/dynamic matcher. Excluded: Faro Olimpo.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from registry.management.commands.reconcile_known_ancestors import _resolve_pair
from registry.models import Dog, Litter
from registry.services import merge_dogs

# Public Bellissimo canonical slug, public archival source ID,
# registration digits independently appearing in both source records.
REVIEWED_PAIRS = (
    ("mia-olimpo-osiride", "67085", "109253"),
    ("plutone", "67083", "1127030"),
    ("aragon", "56990", "1474040"),
    ("rothorm-jy-dream-runaway", "48485", "53116701"),
    ("divina", "46024", "10143704"),
    ("lithium-dellantiqua-apulia", "27371", "10174092"),
    ("anticos-echo", "24917", "30557503"),
    ("fuoco-della-nevaia", "21882", "1015352"),
    ("enza-degli-elmi", "21723", "10164217"),
    ("warrior", "5282", "1221404"),
)


def _guard_merge_relationships(canonical, duplicate):
    """Reject any merge that would collapse sire and dam into one parent."""
    ids = (canonical.pk, duplicate.pk)
    if Dog.objects.filter(
        Q(sire_id=ids[0], dam_id=ids[1])
        | Q(sire_id=ids[1], dam_id=ids[0])
    ).exists():
        raise CommandError(f"Dog parent-pair conflict for {canonical.slug}")
    if Litter.objects.filter(
        Q(sire_id=ids[0], dam_id=ids[1])
        | Q(sire_id=ids[1], dam_id=ids[0])
    ).exists():
        raise CommandError(f"Litter parent-pair conflict for {canonical.slug}")
    # A planned canonical already has no sire/dam, and the source has both,
    # as independently required by _resolve_pair(). Reject any self-parent.
    if duplicate.sire_id in ids or duplicate.dam_id in ids:
        raise CommandError(f"Self-parent conflict for {canonical.slug}")


class Command(BaseCommand):
    help = "Dry-run or atomically reconcile ten registration-verified public ancestors."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Execute verified merges; omit for read-only preview.")
        parser.add_argument("--only",
                            choices=[slug for slug, _, _ in REVIEWED_PAIRS])

    def handle(self, *args, **options):
        selected = tuple(
            pair for pair in REVIEWED_PAIRS
            if not options["only"] or pair[0] == options["only"]
        )
        # Full validation *before* any write. Rollback all merges on error.
        with transaction.atomic():
            checks = []
            for slug, source_id, registration in selected:
                canonical, source = _resolve_pair(slug, source_id, registration)
                if source is not None:
                    _guard_merge_relationships(canonical, source)
                checks.append((slug, source_id, canonical, source))

            for slug, source_id, canonical, source in checks:
                if source is None:
                    self.stdout.write(
                        f"ALREADY RECONCILED: {slug} archive_id={source_id}"
                    )
                else:
                    self.stdout.write(
                        f"IDENTITY VERIFIED: {slug} archive_id={source_id}; "
                        "registration/name/sex/parents checked"
                    )
            if not options["apply"]:
                self.stdout.write(
                    f"DRY RUN: {sum(source is not None for _, _, _, source in checks)} "
                    "eligible merges; no pedigree records changed"
                )
                return

            count = 0
            for slug, source_id, canonical, source in checks:
                if source is None:
                    continue
                history = merge_dogs(canonical, source, performed_by=None)
                count += 1
                self.stdout.write(
                    f"MERGED {history.retired_slug} into {slug} "
                    "(history, sources and redirect preserved)"
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"COMPLETE: {count} verified pairs merged; "
                    f"{len(checks)-count} already reconciled"
                )
            )
