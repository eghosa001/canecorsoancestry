"""Export the exact canonical archive identities for offline breeder research.

Staff-only machine audit use, no credentials, users or kennel ownership fields.
The file is a PRIVATE short-retention Actions artifact, never a public website
endpoint. This command does NOT change any database rows.
"""
import csv
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from registry.models import Dog, DogExternalKey


class Command(BaseCommand):
    help = "Read-only export of unlinked canonical dog IDs and original archive keys."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--max-rows", type=int, default=200000)

    def handle(self, *args, **kwargs):
        target = Path(kwargs["output"])
        limit = kwargs["max_rows"]
        if limit < 0 or limit > 200000:
            raise CommandError("Limit must be between 0 and 200000.")
        # External keys are precise archive identities. Registration numbers
        # and common names are NEVER substituted for source identity.
        keys = {}
        for dog_id, key in DogExternalKey.objects.filter(
            namespace="canecorsopedigree.com", dog__kennel__isnull=True
        ).values_list("dog_id", "key").iterator(chunk_size=3000):
            keys.setdefault(dog_id, []).append(key)
        count = 0
        matched_source = 0
        with target.open("w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow([
                "canonical_dog_id", "registered_name", "archive_source_ids",
                "is_public", "sire_id", "dam_id",
            ])
            for dog in Dog.objects.filter(kennel__isnull=True).only(
                "pk", "name", "is_public", "sire_id", "dam_id",
            ).order_by("pk").iterator(chunk_size=2500):
                count += 1
                if count > limit:
                    raise CommandError("Unexpected dog count: export row safety cap exceeded.")
                source_ids = sorted(
                    (key for key in keys.get(dog.pk, []) if key.isdecimal()),
                    key=int,
                )
                if source_ids:
                    matched_source += 1
                writer.writerow([
                    str(dog.pk), dog.name, ";".join(source_ids),
                    int(dog.is_public), str(dog.sire_id or ""),
                    str(dog.dam_id or ""),
                ])
        self.stdout.write(
            "UNLINKED_ARCHIVE_INVENTORY="
            + f"rows:{count},source_id_matched:{matched_source},"
            + f"without_exact_source_id:{count-matched_source}"
        )
        self.stdout.write("READ-ONLY: no canonical dog or kennel changed.")
