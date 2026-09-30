from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registry.bellissimo_media import media_entries
from registry.models import DogExternalKey, DogImage


class Command(BaseCommand):
    help = "Create idempotent DogImage rows for Bellissimo media already uploaded to R2."

    def add_arguments(self, parser):
        parser.add_argument("source_root")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source_root = Path(options["source_root"])
        try:
            entries, missing, _ = media_entries(source_root)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        created = 0
        existing = 0

        with transaction.atomic():
            managed_keys = set()
            for entry in entries:
                external = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(
                        namespace="bellissimo-geni",
                        key=entry["dog_id"],
                    )
                    .first()
                )
                if external is None:
                    raise CommandError(
                        f"Bellissimo dog is missing from database: {entry['dog_id']}"
                    )

                dog = external.dog
                key = entry["object_key"]
                managed_keys.add(key)

                requested_primary = entry["is_primary"]
                if requested_primary:
                    other_primary = (
                        DogImage.objects.filter(dog=dog, is_primary=True)
                        .exclude(image=key)
                        .exists()
                    )
                    if other_primary:
                        requested_primary = False

                image, was_created = DogImage.objects.update_or_create(
                    dog=dog,
                    image=key,
                    defaults={
                        "caption": "Bellissimo Geni source photograph",
                        "is_primary": requested_primary,
                        "sort_order": entry["sort_order"],
                    },
                )
                created += int(was_created)
                existing += int(not was_created)

            stale = DogImage.objects.filter(
                image__startswith="bellissimo-geni/"
            ).exclude(image__in=managed_keys)
            stale_count = stale.count()
            stale.delete()

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "Dry run" if options["dry_run"] else "Media metadata import complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {created} created, {existing} existing, "
                f"{stale_count} stale removed, {len(entries)} linked, "
                f"{len(missing)} known source files missing."
            )
        )
