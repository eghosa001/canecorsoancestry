"""One-time, resumable CPU WebP backfill for private dog photographs in Cloudflare R2.

Only WRITES new private direct-v2 derivatives, never edits originals or documents.
Requires R2 gateway signing derived from the same Django secret as the Worker.
The Cloudflare REST API token is used for listing object names only.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import hashlib
import hmac
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

BASE = "https://media.canecorsoancestry.com/_r2/"
ACCOUNT_ID = "19a03bec57c0277e01e1e70e241576af"
BUCKET = "canecorsoancestry-media"
SAMPLE = "dogs/2026/11/IMG_6446.jpg"
WIDTHS = {"thumb": 176, "card": 480, "portrait": 960}
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif")
Image.MAX_IMAGE_PIXELS = 36_000_000
# Some archived JPEGs are decodable by a browser but have truncated metadata.
# Never alter the original bytes. This only affects the new lightweight copy.
ImageFile.LOAD_TRUNCATED_IMAGES = True


def is_dog_photo(key: str) -> bool:
    return (key.startswith("dogs/") and ".." not in key.split("/")
            and key.lower().endswith(PHOTO_SUFFIXES))


def direct_key(key: str, variant: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"cca-photo-renditions/direct-v2/{digest}/{variant}.webp"


def make_webps(original: bytes) -> dict[str, bytes]:
    if not original or len(original) > 20_000_000:
        raise ValueError("Image file is empty or exceeds 20 MB processing limit")
    with Image.open(io.BytesIO(original)) as source:
        source.load()
        image = ImageOps.exif_transpose(source)
        if image.width * image.height > 36_000_000:
            raise ValueError("Image dimensions exceed safe processing limit")
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        if image.mode != mode:
            image = image.convert(mode)
        result = {}
        for variant, width in WIDTHS.items():
            if image.width > width:
                height = max(1, round(image.height * width / image.width))
                resized = image.resize((width, height), Image.Resampling.LANCZOS)
            else:
                resized = image
            data = io.BytesIO()
            resized.save(data, "WEBP", quality=79, method=4)
            payload = data.getvalue()
            if payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
                raise ValueError("Pillow did not produce valid WebP bytes")
            result[variant] = payload
        return result


def signed_request(method: str, key: str, *, data: bytes = b"",
                   content_type: str | None = None):
    secret = os.environ["DJANGO_SECRET_KEY"]
    signing_key = base64.b64encode(secret.encode("utf-8"))
    stamp = str(int(time.time()))
    digest = hashlib.sha256(data).hexdigest()
    message = "\n".join((method, key, stamp, digest)).encode("utf-8")
    signature = hmac.new(signing_key, message, hashlib.sha256).hexdigest()
    headers = {
        "X-R2-Timestamp": stamp, "X-R2-Content-SHA256": digest,
        "X-R2-Signature": signature,
        "User-Agent": "CaneCorsoAncestry-WebpBackfill/1.0",
        "Accept": "application/octet-stream, application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    url = BASE + urllib.parse.quote(key, safe="/")
    req = urllib.request.Request(
        url, data=data if method == "PUT" else None,
        headers=headers, method=method,
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, {}
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("R2 request exhausted retries")


def list_source_keys(limit: int) -> list[str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("Cloudflare listing token missing")
    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
        f"/r2/buckets/{BUCKET}/objects"
    )
    keys = []
    cursor = ""
    while len(keys) < limit:
        params = {"prefix": "dogs/", "per_page": 1000}
        if cursor:
            params["cursor"] = cursor
        req = urllib.request.Request(
            endpoint + "?" + urllib.parse.urlencode(params),
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=40) as response:
            result = json.load(response)
        if not result.get("success") or not isinstance(result.get("result"), list):
            raise RuntimeError("Cloudflare R2 object listing was not authorized")
        for item in result["result"]:
            key = item.get("key") or ""
            if is_dog_photo(key):
                keys.append((item.get("last_modified") or "", key))
        info = result.get("result_info") or {}
        new_cursor = info.get("cursor") or ""
        if not info.get("is_truncated") or not new_cursor or new_cursor == cursor:
            break
        cursor = new_cursor
    keys.sort(reverse=True)  # Recently uploaded dog photographs first.
    return [key for _, key in keys[:limit]]


def optimize_one(key: str, *, sample: bool = False) -> tuple[str, int, int]:
    if not is_dog_photo(key):
        return "ignored", 0, 0
    missing = {}
    for variant in WIDTHS:
        name = direct_key(key, variant)
        existing, _ = signed_request("HEAD", name)
        # HEAD has no response body. Only status distinguishes found vs absent.
        # signed_request returns headers for 200 and {} for 404.
        if not _:
            missing[variant] = name
    if not missing:
        return "already_ready", 0, 0

    original, original_headers = signed_request("GET", key)
    if original is None:
        return "missing_source", 0, 0
    versions = make_webps(original)
    original_etag = original_headers.get("ETag", "").strip('"')
    _, current_headers = signed_request("HEAD", key)
    if (original_etag and current_headers.get("ETag", "").strip('"')
            != original_etag):
        return "changed_during_process", 0, 0

    written = 0
    for variant, name in missing.items():
        reply, _ = signed_request(
            "PUT", name, data=versions[variant], content_type="image/webp"
        )
        payload = json.loads(reply or b"{}")
        if payload.get("status") != "stored" or not payload.get("r2_verified"):
            raise RuntimeError("R2 did not verify the WebP rendition upload")
        written += len(versions[variant])
    # Confirm the fast path is now reachable to browsers via the normal
    # signed worker; the original image remains untouched.
    if sample:
        for variant in WIDTHS:
            _, headers = signed_request("HEAD", direct_key(key, variant))
            if not headers:
                raise RuntimeError("Sample rendition is missing after upload")
    return "optimized", len(original), written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-scan", type=int, default=6000)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if (args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count
            or args.workers < 1 or args.workers > 4 or args.limit < 1):
        parser.error("Invalid shard/worker/limit argument")
    if not os.environ.get("DJANGO_SECRET_KEY"):
        raise RuntimeError("Secure R2 gateway signing key is missing")

    # The previously observed broken photo must succeed before backfilling.
    started = time.monotonic()
    status, orig, written = optimize_one(SAMPLE, sample=True)
    print(f"PHOTO_BACKFILL_SAMPLE status={status} orig_bytes={orig} "
          f"webp_bytes={written} seconds={time.monotonic()-started:.2f}",
          flush=True)
    if status not in {"optimized", "already_ready"}:
        raise RuntimeError("The representative failing photo was not repaired")
    if args.sample_only:
        return
    try:
        all_keys = list_source_keys(args.max_scan)
        keys = [
            key for index, key in enumerate(all_keys)
            if index % args.shard_count == args.shard_index and key != SAMPLE
        ]
        print(f"PHOTO_BACKFILL_LIST discovered={len(all_keys)} "
              f"shard={args.shard_index}/{args.shard_count} selected={len(keys)}",
              flush=True)
    except Exception as exc:
        print("PHOTO_BACKFILL_LIST unavailable; targeted sample was repaired "
              f"(reason={type(exc).__name__})", flush=True)
        return

    stats = {"optimized": 0, "already_ready": 0, "failed": 0}
    total_written = 0

    def count_outcome(status, size):
        nonlocal total_written
        if status in stats:
            stats[status] += 1
        else:
            stats["failed"] += 1
        total_written += size
        total = sum(stats.values())
        if total and total % 25 == 0:
            print(f"PHOTO_BACKFILL_PROGRESS scanned={total} "
                  f"optimized={stats['optimized']} already={stats['already_ready']} "
                  f"failed={stats['failed']}", flush=True)

    if args.workers == 1:
        # Scheduled maintenance continues until it finds the requested count
        # of missing images. Already-optimized entries do not waste its quota.
        for key in keys:
            if stats["optimized"] >= args.limit:
                break
            try:
                status, _, size = optimize_one(key)
                count_outcome(status, size)
            except Exception:
                count_outcome("failed", 0)
    else:
        # Cloud-hosted one-time bulk backfill: disjoint sharded source sets,
        # bounded worker concurrency and a finite number of candidates.
        # No original objects are overwritten or published.
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            work = {
                pool.submit(optimize_one, key): key
                for key in keys[:args.limit]
            }
            for future in as_completed(work):
                try:
                    status, _, size = future.result()
                    count_outcome(status, size)
                except Exception:
                    count_outcome("failed", 0)

    print("PHOTO_BACKFILL_TOTAL "
          f"optimized={stats['optimized']} already={stats['already_ready']} "
          f"failed={stats['failed']} bytes_written={total_written}",
          flush=True)


if __name__ == "__main__":
    main()
