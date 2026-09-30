import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registry.models import DogExternalKey, DogImage


DEFAULT_MANIFEST = Path("data/seeds/bellissimo-media.json")


class Command(BaseCommand):
    help = "Attach verified Bellissimo R2 media keys to canonical dog records."

    def add_arguments(self, parser):
        parser.add_argument("manifest", nargs="?", default=str(DEFAULT_MANIFEST))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"])
        if not manifest_path.exists():
            raise CommandError(f"Media manifest not found: {manifest_path}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read media manifest: {exc}") from exc

        namespace = str(manifest.get("namespace") or "").strip()
        items = manifest.get("items")
        if not namespace or not isinstance(items, list):
            raise CommandError("Manifest must contain namespace and items.")

        created = 0
        existing = 0
        skipped_primary = 0

        with transaction.atomic():
            for index, item in enumerate(items):
                external_key = str(item.get("dog_external_key") or "").strip()
                r2_key = str(item.get("r2_key") or "").strip()
                if not external_key or not r2_key:
                    raise CommandError(f"Invalid media item at index {index}.")
                if ".." in r2_key or r2_key.startswith("/"):
                    raise CommandError(f"Unsafe R2 key at index {index}: {r2_key}")

                external = (
                    DogExternalKey.objects.select_related("dog")
                    .filter(namespace=namespace, key=external_key)
                    .first()
                )
                if not external:
                    raise CommandError(
                        f"Dog external key not found: {namespace}:{external_key}"
                    )

                dog = external.dog
                requested_primary = bool(item.get("is_primary"))
                sort_order = int(item.get("sort_order") or 0)

                image = DogImage.objects.filter(dog=dog, image=r2_key).first()
                if image:
                    existing += 1
                else:
                    image = DogImage(dog=dog, image=r2_key)
                    created += 1

                effective_primary = requested_primary
                if requested_primary:
                    other_primary = (
                        DogImage.objects.filter(dog=dog, is_primary=True)
                        .exclude(pk=image.pk)
                        .exists()
                    )
                    if other_primary:
                        effective_primary = False
                        skipped_primary += 1

                changed = (
                    image.pk is None
                    or image.sort_order != sort_order
                    or image.is_primary != effective_primary
                )
                image.sort_order = sort_order
                image.is_primary = effective_primary
                if changed:
                    image.save()

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "Dry run" if options["dry_run"] else "Media import complete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {created} created, {existing} existing, "
                f"{skipped_primary} primary assignment(s) preserved."
            )
        )
