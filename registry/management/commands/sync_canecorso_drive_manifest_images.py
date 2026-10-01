import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.cloudflare_media import gateway_signature, sha256_hex
from registry.models import DogExternalKey, DogImage


DEFAULT_NAMESPACE = "canecorsopedigree.com"
SOURCE_ID_RE = re.compile(r"^(\d+)(?:_|\.)")
ALLOWED_SOURCE_HOSTS = {"canecorsopedigree.com", "www.canecorsopedigree.com"}
ALLOWED_SOURCE_PREFIX = "/static/images/animal/"


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


def validate_source_url(value):
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in ALLOWED_SOURCE_HOSTS
        and parsed.path.startswith(ALLOWED_SOURCE_PREFIX)
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
    )


def retry_session():
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        respect_retry_after_header=True,
    )
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8),
    )
    return session


class Command(BaseCommand):
    help = (
        "Ask the signed Cloudflare media gateway to fetch saved CaneCorso "
        "source-image URLs and persist each verified object directly to R2."
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
        missing_image_file_rows = sorted(manifest_ids - image_file_ids, key=int)
        if missing_image_file_rows:
            raise CommandError(
                f"{len(missing_image_file_rows)} manifest IDs are not recorded as "
                f"downloaded image_file rows in the source CSV."
            )
        invalid_urls = sorted(
            (sid for sid in manifest_ids if not validate_source_url(source_urls[sid])),
            key=int,
        )
        if invalid_urls:
            raise CommandError(
                f"{len(invalid_urls)} archived photo URLs fail the strict source "
                f"allowlist; first IDs: {invalid_urls[:20]}"
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
                    "size": int(item.get("size") or 0),
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

        created = 0
        skipped = 0
        failures = []

        for offset in range(0, len(candidates), batch_size):
            batch = candidates[offset : offset + batch_size]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(self._ingest, item): item
                    for item in batch
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    try:
                        result = future.result()
                        outcome = self._record(item, result["key"], result["size"])
                        if outcome == "created":
                            created += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        failures.append((item, str(exc)))

                    processed = created + skipped + len(failures)
                    if processed % 50 == 0 or processed == len(candidates):
                        self.stdout.write(
                            f"R2 progress: processed={processed}/{len(candidates)}; "
                            f"created={created}; skipped={skipped}; "
                            f"retry_queue={len(failures)}"
                        )

        if failures:
            self.stdout.write(
                f"Retrying {len(failures)} failed Cloudflare ingests sequentially..."
            )
            retry_failures = []
            for number, (item, _) in enumerate(failures, 1):
                try:
                    result = self._ingest(item)
                    outcome = self._record(item, result["key"], result["size"])
                    if outcome == "created":
                        created += 1
                    else:
                        skipped += 1
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
                    f"FAILED source={item['sid']} path={item['path']}: {error}"
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
                f"Cloudflare source → R2 sync complete: created={created}; "
                f"skipped={skipped}; source-linked dogs with managed images={final}."
            )
        )

    def _destination_key(self, item):
        ext = Path(item["path"]).suffix.lower() or ".jpg"
        sid = item["sid"]
        return f"dogs/archive/{int(sid) // 1000:03d}/{sid}{ext}"

    def _ingest(self, item):
        key = self._destination_key(item)
        payload = {
            "url": item["source_url"],
            "expected_size": int(item.get("size") or 0),
        }
        body = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = sha256_hex(body)

        base_url = str(getattr(settings, "R2_GATEWAY_URL", "") or "").rstrip("/")
        if not base_url:
            raise RuntimeError("R2_GATEWAY_URL is not configured")

        endpoint = f"{base_url}/_r2_ingest/{quote(key, safe='/')}"
        last_error = None
        for attempt in range(1, 6):
            timestamp = str(int(time.time()))
            signature = gateway_signature(
                settings.SECRET_KEY,
                "POST",
                key,
                timestamp,
                digest,
            )
            headers = {
                "Content-Type": "application/json",
                "X-R2-Timestamp": timestamp,
                "X-R2-Content-SHA256": digest,
                "X-R2-Signature": signature,
            }
            try:
                with retry_session() as session:
                    response = session.post(
                        endpoint,
                        data=body,
                        headers=headers,
                        timeout=(15, 90),
                    )
                if response.status_code == 201:
                    result = response.json()
                    if result.get("status") != "stored":
                        raise RuntimeError(
                            f"unexpected ingest response: {result!r}"
                        )
                    stored_size = int(result.get("size") or 0)
                    expected = int(item.get("size") or 0)
                    if stored_size <= 0:
                        raise RuntimeError("Cloudflare reported an empty R2 object")
                    if expected and stored_size != expected:
                        raise RuntimeError(
                            f"Cloudflare stored-size mismatch: "
                            f"{stored_size} != {expected}"
                        )
                    remote_size = default_storage.size(key)
                    if remote_size != stored_size:
                        raise RuntimeError(
                            f"R2 HEAD size mismatch: "
                            f"{remote_size} != {stored_size}"
                        )
                    return {"key": key, "size": stored_size}

                detail = response.text[:1000]
                last_error = RuntimeError(
                    f"Cloudflare ingest HTTP {response.status_code}: {detail}"
                )
                if response.status_code in (400, 401, 403, 404, 409, 422):
                    break
            except Exception as exc:
                last_error = exc

            if attempt < 5:
                time.sleep(min(2 ** attempt, 15))

        raise last_error or RuntimeError("Cloudflare ingest failed")

    def _record(self, item, key, stored_size):
        dog_id = item["dog_id"]
        expected = int(item.get("size") or 0)
        if expected and int(stored_size) != expected:
            raise RuntimeError(
                f"Refusing database record for size mismatch: "
                f"{stored_size} != {expected}"
            )

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
