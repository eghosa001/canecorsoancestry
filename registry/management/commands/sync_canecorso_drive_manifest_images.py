import json
import mimetypes
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory

import gdown
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registry.models import DogExternalKey, DogImage


DEFAULT_NAMESPACE = "canecorsopedigree.com"
SOURCE_ID_RE = re.compile(r"^(\d+)(?:_|\.)")


def source_id_from_path(value):
    match = SOURCE_ID_RE.match(Path(value).name)
    if not match:
        return ""
    return match.group(1).lstrip("0") or "0"


def load_manifest(index_path):
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = int(index.get("file_count") or 0)
    entries = []
    for segment in index.get("segments", []):
        segment_path = Path(segment["path"])
        rows = [
            json.loads(line)
            for line in segment_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != int(segment["count"]):
            raise CommandError(
                f"Manifest segment count mismatch for {segment_path}: "
                f"{len(rows)} != {segment['count']}"
            )
        entries.extend(rows)

    if len(entries) != expected:
        raise CommandError(
            f"Manifest total mismatch: {len(entries)} != {expected}"
        )
    ids = [item["id"] for item in entries]
    paths = [item["path"] for item in entries]
    if len(set(ids)) != len(ids):
        raise CommandError("Drive manifest contains duplicate file IDs.")
    if len(set(paths)) != len(paths):
        raise CommandError("Drive manifest contains duplicate paths.")

    for raw in paths:
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            raise CommandError(f"Unsafe manifest path: {raw}")

    return entries


class Command(BaseCommand):
    help = (
        "Download missing CaneCorso archive photos by fixed Drive file ID and "
        "persist each verified image directly to Cloudflare R2."
    )

    def add_arguments(self, parser):
        parser.add_argument("manifest_index")
        parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        index_path = Path(options["manifest_index"])
        if not index_path.is_file():
            raise CommandError(f"Manifest index not found: {index_path}")

        namespace = options["namespace"].strip()
        workers = max(1, min(int(options["workers"]), 16))
        batch_size = max(workers, min(int(options["batch_size"]), 500))
        entries = load_manifest(index_path)

        by_source = {}
        malformed = []
        for item in entries:
            sid = source_id_from_path(item["path"])
            if not sid:
                malformed.append(item["path"])
                continue
            previous = by_source.get(sid)
            score = (int(item.get("size") or 0), item["path"])
            if previous is None:
                by_source[sid] = item
            else:
                old_score = (int(previous.get("size") or 0), previous["path"])
                if score > old_score:
                    by_source[sid] = item

        external_rows = list(
            DogExternalKey.objects.filter(namespace=namespace)
            .values_list("key", "dog_id")
        )
        if not external_rows:
            raise CommandError(f"No DogExternalKey rows found for {namespace!r}.")

        linked_dog_ids = {dog_id for _, dog_id in external_rows}
        existing_dog_ids = set(
            DogImage.objects.filter(dog_id__in=linked_dog_ids)
            .values_list("dog_id", flat=True)
        )

        candidates = []
        planned_dogs = set()
        missing_archive = []
        for sid, dog_id in external_rows:
            if dog_id in existing_dog_ids or dog_id in planned_dogs:
                continue
            item = by_source.get(sid)
            if item is None:
                missing_archive.append(sid)
                continue
            candidates.append(
                {
                    "sid": sid,
                    "dog_id": dog_id,
                    "id": item["id"],
                    "path": item["path"],
                    "size": item.get("size"),
                }
            )
            planned_dogs.add(dog_id)

        candidates.sort(key=lambda item: int(item["sid"]))
        possible_coverage = len(existing_dog_ids) + len(planned_dogs)
        if possible_coverage < 9000:
            raise CommandError(
                "Archive cannot satisfy 9000-photo coverage: "
                f"existing={len(existing_dog_ids)}, planned={len(planned_dogs)}, "
                f"possible={possible_coverage}"
            )

        if options["limit"] > 0:
            candidates = candidates[: options["limit"]]

        self.stdout.write(
            "Manifest sync preflight: "
            f"{len(entries)} physical image files; "
            f"{len(by_source)} source photo IDs; "
            f"{len(linked_dog_ids)} linked source dogs; "
            f"{len(existing_dog_ids)} already have managed images; "
            f"{len(candidates)} selected for this run; "
            f"{len(missing_archive)} linked source IDs have no archived image; "
            f"{len(malformed)} malformed archive filenames."
        )

        if options["dry_run"] or not candidates:
            return

        with TemporaryDirectory(prefix="canecorso-r2-sync-") as temp_name:
            temp_root = Path(temp_name)
            created = 0
            skipped = 0
            failures = []

            for offset in range(0, len(candidates), batch_size):
                batch = candidates[offset : offset + batch_size]
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    future_map = {
                        pool.submit(self._download, item, temp_root): item
                        for item in batch
                    }
                    for future in as_completed(future_map):
                        item = future_map[future]
                        try:
                            local_path = future.result()
                        except Exception as exc:
                            failures.append((item, f"download: {exc}"))
                            continue

                        try:
                            outcome = self._persist(item, local_path)
                            if outcome == "created":
                                created += 1
                            else:
                                skipped += 1
                        except Exception as exc:
                            failures.append((item, f"r2/database: {exc}"))
                        finally:
                            local_path.unlink(missing_ok=True)

                        processed = created + skipped + len(failures)
                        if processed % 50 == 0:
                            self.stdout.write(
                                f"R2 progress: processed={processed}/{len(candidates)}; "
                                f"created={created}; skipped={skipped}; "
                                f"retry_queue={len(failures)}"
                            )

            if failures:
                self.stdout.write(
                    f"Retrying {len(failures)} failed photo syncs sequentially..."
                )
                retry_failures = []
                for number, (item, _) in enumerate(failures, 1):
                    try:
                        local_path = self._download(item, temp_root)
                        outcome = self._persist(item, local_path)
                        if outcome == "created":
                            created += 1
                        else:
                            skipped += 1
                        local_path.unlink(missing_ok=True)
                    except Exception as exc:
                        retry_failures.append((item, str(exc)))
                    if number % 25 == 0 or number == len(failures):
                        self.stdout.write(
                            f"Retry progress: {number}/{len(failures)}; "
                            f"still_failed={len(retry_failures)}"
                        )
                failures = retry_failures

            if failures:
                for item, error in failures[:25]:
                    self.stderr.write(
                        f"FAILED source={item['sid']} drive={item['id']} "
                        f"path={item['path']}: {error}"
                    )
                raise CommandError(
                    f"{len(failures)} required photos still failed after retries."
                )

        final = (
            DogImage.objects.filter(dog_id__in=linked_dog_ids)
            .values("dog_id")
            .distinct()
            .count()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Direct Drive → R2 sync complete: created={created}; "
                f"skipped={skipped}; source-linked dogs with managed images={final}."
            )
        )

    def _download(self, item, temp_root):
        suffix = Path(item["path"]).suffix.lower() or ".jpg"
        target = temp_root / f"{item['sid']}{suffix}"
        expected = int(item.get("size") or 0)

        for timeout, retries in ((30, 5), (60, 10), (90, 12)):
            try:
                result = gdown.download(
                    id=item["id"],
                    output=str(target),
                    quiet=True,
                    use_cookies=False,
                    resume=True,
                    timeout=timeout,
                    retries=retries,
                )
                if result and target.is_file() and target.stat().st_size > 0:
                    if not expected or target.stat().st_size == expected:
                        return target
            except Exception:
                pass
            time.sleep(1)

        actual = target.stat().st_size if target.exists() else 0
        raise RuntimeError(
            f"Drive download did not verify after retries "
            f"(expected={expected or 'non-empty'}, actual={actual})"
        )

    def _persist(self, item, local_path):
        dog_id = item["dog_id"]
        if DogImage.objects.filter(dog_id=dog_id).exists():
            return "skipped"

        sid = item["sid"]
        ext = local_path.suffix.lower()
        key = f"dogs/archive/{int(sid) // 1000:03d}/{sid}{ext}"
        data = local_path.read_bytes()
        if not data:
            raise RuntimeError("Downloaded file is empty")

        content_type = (
            mimetypes.guess_type(item["path"])[0]
            or "application/octet-stream"
        )

        last_error = None
        for attempt in range(1, 6):
            try:
                content = ContentFile(data, name=local_path.name)
                content.content_type = content_type
                if hasattr(default_storage, "save_exact"):
                    default_storage.save_exact(key, content)
                else:
                    if default_storage.exists(key):
                        default_storage.delete(key)
                    default_storage.save(key, content)

                remote_size = default_storage.size(key)
                if remote_size != len(data):
                    raise RuntimeError(
                        f"R2 size mismatch for {key}: {remote_size} != {len(data)}"
                    )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < 5:
                    time.sleep(min(2 ** attempt, 15))

        if last_error is not None:
            raise last_error

        with transaction.atomic():
            if DogImage.objects.filter(dog_id=dog_id).exists():
                return "skipped"
            DogImage.objects.create(
                dog_id=dog_id,
                image=key,
                caption=(
                    "Archived source photo · "
                    "CaneCorsoPedigree.com snapshot 2026-09-15"
                ),
                is_primary=True,
                sort_order=0,
            )
        return "created"
