"""Copy already-owned media from R2 into the persistent Oracle volume.

This is a resumable, never-delete-the-source migration. It does not bypass an
R2 billing suspension: original files or a separate backup must be available.
"""
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db.models import FileField

from core.r2_gateway_storage import CloudflareR2GatewayStorage


def referenced_media_keys():
    """Read existing FileField names only; never invent or scrape media."""
    seen = set()
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if not isinstance(field, FileField):
                continue
            rows = model._base_manager.exclude(**{field.name: ""}).values_list(
                field.attname, flat=True
            ).iterator(chunk_size=1000)
            for name in rows:
                name = str(name or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    yield name


def safe_target(root, name):
    # Storage keys always use POSIX paths, regardless of host platform.
    key = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(part in ("", ".", "..") for part in name.split("/"))
        or key.is_absolute()
    ):
        raise ValueError("Unsafe existing media key")
    target = (root / Path(*key.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Media key escapes the Oracle volume")
    return target


class Command(BaseCommand):
    help = "Copy R2-managed, database-referenced media into Oracle disk (dry-run unless --write)."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--prefix", default="")

    def handle(self, *args, **options):
        if getattr(settings, "CCA_MEDIA_BACKEND", "r2") != "oracle-local":
            raise CommandError(
                "Run with CCA_MEDIA_BACKEND=oracle-local and a persistent /app/media mount."
            )
        if options["limit"] < 0:
            raise CommandError("--limit cannot be negative")
        root = Path(settings.MEDIA_ROOT).resolve()
        if not root.is_dir():
            raise CommandError("Persistent Oracle media volume is not mounted.")
        if not options["write"]:
            self.stdout.write("DRY RUN: no downloads and no media writes will occur")

        upstream = CloudflareR2GatewayStorage()
        copied = existing = missing = failed = 0
        for key in referenced_media_keys():
            if options["prefix"] and not key.startswith(options["prefix"]):
                continue
            try:
                destination = safe_target(root, key)
            except ValueError:
                failed += 1
                continue
            if destination.exists():
                if destination.is_file() and destination.stat().st_size > 0:
                    existing += 1
                else:
                    failed += 1
                continue

            missing += 1
            if options["limit"] and missing > options["limit"]:
                break
            if not options["write"]:
                continue
            if shutil.disk_usage(root).free < 2 * 1024**3:
                raise CommandError("Less than 2 GiB free: stopping before the volume fills.")

            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = None
            try:
                # Stream directly from R2's signed HTTP response to bounded
                # disk chunks, never loading full-resolution files into memory.
                with upstream._request(key, method="GET") as remote:
                    fd, partial = tempfile.mkstemp(
                        prefix=".cca-restore-", dir=destination.parent
                    )
                    with os.fdopen(fd, "wb") as target:
                        shutil.copyfileobj(remote, target, length=1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
                if os.path.getsize(partial) == 0:
                    raise OSError("Empty R2 object")
                os.chmod(partial, 0o640)
                try:
                    # Never replace a concurrently uploaded file or discard an
                    # already working copy. The source object is never deleted.
                    os.link(partial, destination)
                    copied += 1
                except FileExistsError:
                    existing += 1
            except Exception as exc:
                failed += 1
                if failed <= 5:
                    self.stderr.write(
                        "Copy failed (key omitted): " + type(exc).__name__
                    )
            finally:
                if partial is not None:
                    Path(partial).unlink(missing_ok=True)

        self.stdout.write(
            f"Oracle media recovery: copied={copied} existing={existing} "
            f"needed={missing} failed={failed}"
        )
        if failed:
            raise CommandError(
                "Some objects could not be recovered; keep R2 data and use original backups."
            )
