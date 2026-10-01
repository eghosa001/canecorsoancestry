import csv
import mimetypes
import re
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registry.models import DogExternalKey, DogImage


DEFAULT_NAMESPACE = "canecorsopedigree.com"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def source_id(value):
    try:
        return str(int(float(str(value).strip())))
    except (TypeError, ValueError):
        return ""


def archive_filename(value):
    raw = str(value or "").strip().replace("\\", "/")
    return raw.rsplit("/", 1)[-1] if raw else ""


class Command(BaseCommand):
    help = "Upload archived CaneCorsoPedigree dog photos to configured object storage."

    def add_arguments(self, parser):
        parser.add_argument("source_csv")
        parser.add_argument("image_root")
        parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        source_csv = Path(options["source_csv"])
        image_root = Path(options["image_root"])
        namespace = options["namespace"].strip()

        if not source_csv.is_file():
            raise CommandError(f"Source CSV not found: {source_csv}")
        if not image_root.is_dir():
            raise CommandError(f"Image root not found: {image_root}")
        if not namespace:
            raise CommandError("Namespace cannot be blank.")

        external = {
            item.key: item
            for item in DogExternalKey.objects.select_related("dog").filter(
                namespace=namespace
            )
        }
        if not external:
            raise CommandError(f"No DogExternalKey rows found for {namespace!r}.")

        existing_dog_ids = set(
            DogImage.objects.filter(dog_id__in=[item.dog_id for item in external.values()])
            .values_list("dog_id", flat=True)
        )

        records = {}
        with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                sid = source_id(row.get("id"))
                if sid not in external:
                    continue
                filename = archive_filename(row.get("image_file"))
                if filename:
                    records[sid] = filename

        local_by_source = {}
        for path in image_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            match = re.match(r"^(\d+)_", path.name)
            if match:
                local_by_source.setdefault(match.group(1), path)

        candidates = []
        missing_files = []
        for sid, filename in records.items():
            item = external[sid]
            if item.dog_id in existing_dog_ids:
                continue
            path = local_by_source.get(sid)
            if path is None:
                missing_files.append((sid, filename))
                continue
            candidates.append((sid, item.dog, path))

        candidates.sort(key=lambda item: int(item[0]))
        if options["limit"] > 0:
            candidates = candidates[: options["limit"]]

        self.stdout.write(
            f"Archive media preflight: {len(external)} linked dogs; "
            f"{len(records)} mapped archive photos; {len(existing_dog_ids)} dogs already have "
            f"managed images; {len(candidates)} photos ready; {len(missing_files)} mapped files missing locally."
        )

        if options["dry_run"]:
            return

        uploaded = 0
        created = 0
        skipped = 0

        for sid, dog, path in candidates:
            if DogImage.objects.filter(dog=dog).exists():
                skipped += 1
                continue

            ext = path.suffix.lower()
            key = f"dogs/archive/{int(sid) // 1000:03d}/{sid}{ext}"
            data = path.read_bytes()
            if not data:
                self.stderr.write(f"Skipping empty archive image: {path}")
                skipped += 1
                continue

            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            content = ContentFile(data, name=path.name)
            content.content_type = content_type

            if hasattr(default_storage, "save_exact"):
                default_storage.save_exact(key, content)
            else:
                if default_storage.exists(key):
                    default_storage.delete(key)
                default_storage.save(key, content)
            uploaded += 1

            with transaction.atomic():
                if DogImage.objects.filter(dog=dog).exists():
                    skipped += 1
                    continue
                DogImage.objects.create(
                    dog=dog,
                    image=key,
                    caption="Archived source photo · CaneCorsoPedigree.com snapshot 2026-09-15",
                    is_primary=True,
                    sort_order=0,
                )
                created += 1

            if created % 250 == 0:
                self.stdout.write(f"Imported {created} archived dog photos...")

        final = DogImage.objects.filter(
            dog_id__in=[item.dog_id for item in external.values()]
        ).values("dog_id").distinct().count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Archive media import complete: uploaded={uploaded}; created={created}; "
                f"skipped={skipped}; source-linked dogs with managed images={final}."
            )
        )
