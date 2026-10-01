import csv
import json
import mimetypes
import re
import threading
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
_thread_local = threading.local()


def source_id(value):
    try:
        return str(int(float(str(value).strip())))
    except (TypeError, ValueError):
        return ""


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


def load_source_urls(source_csv):
    urls = {}
    image_file_ids = set()
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = source_id(row.get("id"))
            if not sid:
                continue
            image_url = str(row.get("image_url") or "").strip()
            image_file = str(row.get("image_file") or "").strip()
            if image_url:
                urls[sid] = image_url
            if image_file:
                image_file_ids.add(sid)
    return urls, image_file_ids


def http_session():
    session = getattr(_thread_local, "session", None)
    if session is not None:
        return session
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.canecorsopedigree.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
    )
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8),
    )
    _thread_local.session = session
    return session


class Command(BaseCommand):
    help = (
        "Fetch missing CaneCorso archive photos from their saved original image "
        "URLs and persist each verified image directly to Cloudflare R2."
    )

    def add_arguments(self, parser):
        parser.add_argument("manifest_index")
        parser.add_argument("source_csv")
        parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--workers", type=int, default=6)
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
        workers = max(1, min(int(options["workers"]), 8))
        batch_size = max(workers, min(int(options["batch_size"]), 500))
        entries = load_manifest(index_path)
        source_urls, image_file_ids = load_source_urls(source_csv)

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

        manifest_ids = set(by_source)
        missing_urls = sorted(manifest_ids - set(source_urls), key=int)
        if missing_urls:
            raise CommandError(
                f"{len(missing_urls)} archived photo IDs have no saved original "
                f"image_url; first IDs: {missing_urls[:20]}"
            )
        missing_image_file_rows = sorted(
            manifest_ids - image_file_ids,
            key=int,
        )
        if missing_image_file_rows:
            raise CommandError(
                f"{len(missing_image_file_rows)} manifest IDs are not recorded as "
                f"downloaded image_file rows in the source CSV."
            )

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
                    "drive_id": item["id"],
                    "path": item["path"],
                    "size": item.get("size"),
                    "source_url": source_urls[sid],
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
            f"{len(source_urls)} saved source image URLs; "
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
                        f"FAILED source={item['sid']} "
                        f"url={item['source_url']} path={item['path']}: {error}"
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
                f"skipped={skipped}; source-linked dogs with managed images={final}."
            )
        )

    def _download(self, item, temp_root):
        suffix = Path(item["path"]).suffix.lower() or ".jpg"
        target = temp_root / f"{item['sid']}{suffix}"
        partial = target.with_suffix(target.suffix + ".part")
        expected = int(item.get("size") or 0)

        last_error = None
        for timeout in (30, 60, 90):
            try:
                partial.unlink(missing_ok=True)
                response = http_session().get(
                    item["source_url"],
                    timeout=timeout,
                    stream=True,
                )
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type") or ""
                ).split(";", 1)[0].lower()
                if not content_type.startswith("image/"):
                    raise RuntimeError(
                        f"non-image content-type: {content_type or 'missing'}"
                    )

                with partial.open("wb") as handle:
                    for chunk in response.iter_content(256 * 1024):
                        if chunk:
                            handle.write(chunk)

                actual = partial.stat().st_size if partial.exists() else 0
                if actual <= 0:
                    raise RuntimeError("empty image response")
                if expected and actual != expected:
                    raise RuntimeError(
                        f"source size mismatch: expected={expected}, actual={actual}"
                    )

                partial.replace(target)
                return target
            except Exception as exc:
                last_error = exc
                time.sleep(1)

        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"source image download failed after retries: {last_error}"
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
