"""Restore existing, consented dog images from the owner's Drive archive.

The input directory is a *local copy* of clean_v4_1/images. This command
never changes dog identities or the DogImage table, never downloads from
untrusted URLs, and never overwrites already working media.
"""

import os
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.models import DogImage

ARCHIVE_NAME = re.compile(r"^(\d+)(?:_|\.)[^/]*\.(jpg|jpeg|png|webp|gif)$", re.I)


def source_key(filename):
    match = ARCHIVE_NAME.fullmatch(filename)
    if match is None:
        return ""
    sid = int(match.group(1))
    return f"dogs/archive/{sid // 1000:03d}/{sid}.{match.group(2).lower()}"


class Command(BaseCommand):
    help = "Restore known dog photos from a local copy of the owner's Drive archive."

    def add_arguments(self, parser):
        parser.add_argument("archive_root")
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        if getattr(settings, "CCA_MEDIA_BACKEND", "r2") != "oracle-local":
            raise CommandError("Use CCA_MEDIA_BACKEND=oracle-local to restore images.")
        archive = Path(options["archive_root"]).resolve()
        root = Path(settings.MEDIA_ROOT).resolve()
        if not archive.is_dir() or not root.is_dir():
            raise CommandError("Archive and persistent Oracle media root must both exist.")
        if options["limit"] < 0:
            raise CommandError("--limit cannot be negative")
        if not options["write"]:
            self.stdout.write("DRY RUN: no media writes")

        # Database file references are authoritative. A filename is not enough
        # to associate a photograph with any new or different dog.
        expected = set(
            DogImage.objects.filter(image__startswith="dogs/archive/")
            .exclude(image="")
            .values_list("image", flat=True)
        )
        sources = defaultdict(list)
        for source in archive.rglob("*"):
            if source.is_file() and not source.is_symlink():
                key = source_key(source.name)
                if key in expected:
                    sources[key].append(source)

        copied = existing = missing = ambiguous = 0
        for key in sorted(expected):
            target = (root / key).resolve()
            if not target.is_relative_to(root):
                raise CommandError("Database media key escapes Oracle media root")
            if target.exists():
                if not target.is_file() or target.stat().st_size == 0:
                    raise CommandError("Existing image path is empty or not a file")
                existing += 1
                continue
            choices = sources.get(key, [])
            if not choices:
                missing += 1
                continue
            if len(choices) > 1:
                ambiguous += 1
                continue
            if options["limit"] and copied >= options["limit"]:
                break
            if not options["write"]:
                copied += 1  # count actionable copies without writing
                continue
            if shutil.disk_usage(root).free < 2 * 1024**3:
                raise CommandError("Less than 2 GiB free on Oracle; stopping recovery.")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = None
            try:
                fd, partial = tempfile.mkstemp(prefix=".cca-archive-", dir=target.parent)
                with os.fdopen(fd, "wb") as out, choices[0].open("rb") as src:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
                if os.path.getsize(partial) == 0:
                    raise CommandError("Archived dog image is empty")
                os.chmod(partial, 0o640)
                try:
                    os.link(partial, target)
                    copied += 1
                except FileExistsError:
                    existing += 1
            finally:
                if partial is not None:
                    Path(partial).unlink(missing_ok=True)

        self.stdout.write(
            f"Archive recovery: referenced={len(expected)} recovered_or_ready={copied} "
            f"already_present={existing} no_source={missing} ambiguous={ambiguous}"
        )
        if options["write"] and ambiguous:
            raise CommandError("Ambiguous archived photos require manual identity review.")
