import csv
import json
import mimetypes
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from registry.models import DogExternalKey, DogImage


DEFAULT_NAMESPACE = "canecorsopedigree.com"
SOURCE_ID_RE = re.compile(r"^(\d+)(?:_|\.)")
USER_AGENT = (
    "CaneCorsoResearchArchiver/1.0 "
    "(+personal archival/research; respectful rate-limited crawler)"
)


def source_id_from_path(value):
    match = SOURCE_ID_RE.match(Path(value).name)
    if not match:
        return ""
    return match.group(1).lstrip("0") or "0"


def source_id(value):
    try:
        return str(int(float(str(value).strip())))
    except (TypeError, ValueError):
        return ""


def archive_filename(value):
    raw = str(value or "").strip().replace("\\", "/")
    return raw.rsplit("/", 1)[-1] if raw else ""


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


def build_session():
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=16,
        pool_maxsize=16,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class Command(BaseCommand):
    help = (
        "Re-fetch archived CaneCorso source images from their original public "
        "image URLs and persist each verified image directly to Cloudflare R2."
    )

    def add_arguments(self, parser):
        parser.add_argument("manifest_index")
        parser.add_argument("source_csv")
        parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        index_path = Path(options["manifest_index"])
        source_csv = Path(options["source_csv"])
        if not index_path.is_file():
            raise CommandError(f"Manifest index not found: {index_path}")
        if not source_csv.is_file():
            raise CommandError(f"Source CSV not found: {source_csv}")

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
            by_source[sid] = item

        csv_rows = {}
        with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                sid = source_id(row.get("id"))
                if not sid:
                    continue
                image_url = str(row.get("image_url") or "").strip()
                image_file = archive_filename(row.get("image_file"))
                if image_url or image_file:
                    csv_rows[sid] = {
                        "image_url": image_url,
                        "image_file": image_file,
                    }

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
        missing_url = []
        for sid, dog_id in external_rows:
            if dog_id in existing_dog_ids or dog_id in planned_dogs:
                continue
            archived = by_source.get(sid)
            if archived is None:
                missing_archive.append(sid)
                continue
            csv_item = csv_rows.get(sid) or {}
            image_url = csv_item.get("image_url") or ""
            if not image_url:
                missing_url.append(sid)
                continue

            candidates.append(
                {
                    "sid": sid,
                    "dog_id": dog_id,
                    "url": image_url,
                    "path": archived["path"],
                    "expected_size": int(archived.get("size") or 0),
                    "csv_image_file": csv_item.get("image_file") or "",
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
            "Source-image sync preflight: "
            f"{len(entries)} archived image files; "
            f"{len(by_source)} archived source photo IDs; "
            f"{len(csv_rows)} CSV rows with image metadata; "
            f"{len(linked_dog_ids)} linked source dogs; "
            f"{len(existing_dog_ids)} already have managed images; "
            f"{len(candidates)} selected for this run; "
            f"{len(missing_archive)} linked source IDs have no archived image; "
            f"{len(missing_url)} archived source IDs have no original image URL; "
            f"{len(malformed)} malformed archive filenames."
        )

        if options["dry_run"] or not candidates:
            return

        with TemporaryDirectory(prefix="canecorso-r2-sync-") as temp_name:
            temp_root = Path(temp_name)
            created = 0
            skipped = 0
            warnings = 0
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
                            local_path, size_warning = future.result()
                            if size_warning:
                                warnings += 1
                                self.stderr.write(
                                    self.style.WARNING(size_warning)
                                )
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
                                f"retry_queue={len(failures)}; warnings={warnings}"
                            )

            if failures:
                self.stdout.write(
                    f"Retrying {len(failures)} failed photo syncs sequentially..."
                )
                retry_failures = []
                for number, (item, _) in enumerate(failures, 1):
                    try:
                        local_path, size_warning = self._download(
                            item, temp_root, final_retry=True
                        )
                        if size_warning:
                            warnings += 1
                            self.stderr.write(self.style.WARNING(size_warning))
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
                        f"FAILED source={item['sid']} "
                        f"url={item['url']} path={item['path']}: {error}"
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
                f"Direct source → R2 sync complete: created={created}; "
                f"skipped={skipped}; warnings={warnings}; "
                f"source-linked dogs with managed images={final}."
            )
        )

    def _download(self, item, temp_root, final_retry=False):
        suffix = Path(item["path"]).suffix.lower() or ".jpg"
        target = temp_root / f"{item['sid']}{suffix}"
        expected = int(item.get("expected_size") or 0)
        timeout = (20, 90) if final_retry else (10, 45)

        session = build_session()
        try:
            response = session.get(
                item["url"],
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = (
                response.headers.get("content-type") or ""
            ).split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                raise RuntimeError(
                    f"non-image content-type: {content_type or 'missing'}"
                )

            total = 0
            with target.open("wb") as handle:
                for chunk in response.iter_content(256 * 1024):
                    if chunk:
                        handle.write(chunk)
                        total += len(chunk)

            if total <= 0:
                raise RuntimeError("empty image body")

            size_warning = ""
            if expected and total != expected:
                size_warning = (
                    f"Source {item['sid']} image size changed since archive: "
                    f"archived={expected}, current={total}; "
                    "using current verified image bytes."
                )
            return target, size_warning
        finally:
            session.close()

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
