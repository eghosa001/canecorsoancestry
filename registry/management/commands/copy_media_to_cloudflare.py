import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from core.media_migration import body_sha256, migration_signature
from registry.models import DisputeCase, DogDocument, DogImage, DogSource, Submission


MEDIA_FIELDS = (
    (DogImage, "image"),
    (DogDocument, "file"),
    (DogSource, "document"),
    (Submission, "attachment"),
    (DisputeCase, "attachment"),
)


def referenced_media_paths():
    paths = set()
    for model, field in MEDIA_FIELDS:
        paths.update(
            value
            for value in model._default_manager.exclude(
                **{field: ""}
            ).values_list(field, flat=True)
            if value
        )
    return sorted(paths)


def _validated_target(raw):
    value = (raw or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https":
        raise CommandError("Cloudflare preview URL must use HTTPS.")
    host = (parsed.hostname or "").lower()
    if not host.endswith(".workers.dev"):
        raise CommandError(
            "Cloudflare media migration target must be a workers.dev preview."
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise CommandError("Cloudflare preview URL must be an origin URL only.")
    return value


class Command(BaseCommand):
    help = (
        "Copy every database-referenced production media object from the current "
        "Django storage backend to the authenticated Cloudflare R2 preview importer."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--target-url",
            default=os.getenv("CLOUDFLARE_PREVIEW_URL", ""),
            help="HTTPS workers.dev preview origin.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate source media without uploading it.",
        )

    def handle(self, *args, **options):
        target = _validated_target(options["target_url"])
        paths = referenced_media_paths()
        max_size = int(
            getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 25 * 1024 * 1024)
        )

        missing = []
        uploaded = 0
        existing = 0
        checked = 0

        for path in paths:
            if not default_storage.exists(path):
                missing.append(path)
                continue

            size = default_storage.size(path)
            if size > max_size:
                raise CommandError(
                    f"Media object exceeds the {max_size}-byte migration limit: {path}"
                )

            checked += 1
            if options["dry_run"]:
                continue

            with default_storage.open(path, "rb") as handle:
                body = handle.read()

            digest = body_sha256(body)
            timestamp = str(int(time.time()))
            signature = migration_signature(
                settings.SECRET_KEY,
                timestamp,
                path,
                digest,
            )
            encoded_path = urllib.parse.quote(path, safe="/")
            request = urllib.request.Request(
                f"{target}/internal/media-import/{encoded_path}",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Migration-Timestamp": timestamp,
                    "X-Migration-Signature": signature,
                    "User-Agent": "CaneCorsoAncestry-Media-Migration/1",
                },
            )

            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise CommandError(
                    f"Cloudflare rejected media migration for {path}: HTTP {exc.code}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise CommandError(
                    f"Cloudflare media migration failed for {path}: {exc}"
                ) from exc

            if (
                payload.get("path") != path
                or payload.get("size") != len(body)
                or payload.get("sha256") != digest
            ):
                raise CommandError(
                    f"Cloudflare verification mismatch for media object: {path}"
                )

            if payload.get("status") == "stored":
                uploaded += 1
            elif payload.get("status") == "exists":
                existing += 1
            else:
                raise CommandError(
                    f"Unexpected Cloudflare media status for {path}: "
                    f"{payload.get('status')!r}"
                )

        if missing:
            preview = ", ".join(missing[:5])
            suffix = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
            raise CommandError(
                f"{len(missing)} database-referenced media object(s) are missing "
                f"from source storage: {preview}{suffix}"
            )

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Media dry-run passed: {checked} referenced object(s) are present."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Cloudflare media migration verified: "
                f"{uploaded} stored, {existing} already identical, "
                f"{checked} total."
            )
        )
