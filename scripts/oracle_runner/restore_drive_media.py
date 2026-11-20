#!/usr/bin/env python3
"""Restore pre-existing CaneCorso dog photographs from the owner's Drive archive.

Only write files already referenced by production DogImage records, and only to
their existing media keys. Never update a dog, expose private documents, or
delete/overwrite files.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "data/canecorso_drive_manifest_v1/index.json"
ROOT = Path("/var/lib/cca/media")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SIGNS = (
    bytes.fromhex("ffd8ff"),  # jpeg
    bytes.fromhex("89504e470d0a1a0a"),  # png
    b"GIF8", b"RIFF",  # gif, webp (verified below)
)


def dog_image_keys():
    code = (
        "import os,json,django;"
        "django.setup();"
        "from registry.models import DogImage;"
        "print(json.dumps(list(DogImage.objects.values_list('image',flat=True))))"
    )
    result = subprocess.run(
        ["sudo", "-n", "podman", "exec", "cca-oracle-staging",
         "python", "-c", code],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        timeout=90,
    )
    return set(json.loads(result.stdout))


def manifest():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    files = {}
    for entry in index["segments"]:
        filename = REPO_ROOT / entry["path"]
        for line in filename.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            name = Path(item["path"]).name
            raw_id = name.split("_", 1)[0]
            if not raw_id.isdigit():
                continue
            source_id = int(raw_id)
            extension = Path(name).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".webp", ".png", ".gif"}:
                continue
            # This is the canonical pre-existing importer key format.
            key = f"dogs/archive/{source_id // 1000:03d}/{source_id}{extension}"
            prior = files.get(key)
            if prior is None or int(item.get("size", 0)) > int(prior.get("size", 0)):
                files[key] = item
    return files


def valid_image(payload):
    if payload.startswith(b"\xff\xd8\xff") or payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return True
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return True
    return False


def recover(key, record):
    dest = (ROOT / key).resolve()
    if not dest.is_relative_to(ROOT.resolve()):
        return "unsafe"
    if dest.is_file() and dest.stat().st_size > 0:
        return "existing"
    if dest.exists():
        return "blocked"
    directory = dest.parent
    directory.mkdir(parents=True, exist_ok=True)
    drive_id = record["id"]
    url = "https://drive.google.com/uc?" + urlencode(
        {"export": "download", "id": drive_id}
    )
    expected = int(record.get("size") or 0)
    if expected < 100 or expected > MAX_IMAGE_BYTES:
        return "bad-size"
    for attempt in range(5):
        temp = None
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 CaneCorsoAncestry-Recovery/1.0",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*",
            })
            with urlopen(req, timeout=35) as response:
                mime = response.headers.get_content_type()
                if not mime.startswith("image/"):
                    raise ValueError("non-image payload from Drive")
                fd, temp = tempfile.mkstemp(prefix=".drive-recover-", dir=directory)
                received = 0
                first = b""
                with os.fdopen(fd, "wb") as output:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        if received == 0:
                            first = chunk[:16]
                        received += len(chunk)
                        if received > MAX_IMAGE_BYTES:
                            raise ValueError("oversized download")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if received != expected or not valid_image(first):
                raise ValueError("image size/type mismatch")
            os.chmod(temp, 0o640)
            try:
                os.link(temp, dest)
                return "restored"
            except FileExistsError:
                return "existing"
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            if attempt < 4:
                time.sleep(min(2 ** attempt, 12) + random.random())
        finally:
            if temp:
                Path(temp).unlink(missing_ok=True)
    return "failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Must run as root on the protected Oracle self-hosted runner")
    if not ROOT.is_dir():
        raise SystemExit("Persistent media directory is not mounted")
    if shutil.disk_usage(ROOT).free < 4 * 1024 ** 3:
        raise SystemExit("Not enough free space for safe media restoration")

    keys = dog_image_keys()
    references = sorted(key for key in keys if key.startswith("dogs/archive/"))
    sources = manifest()
    matched = [key for key in references if key in sources]
    mismatched = len(references) - len(matched)
    already = sum(1 for key in references
                  if (ROOT / key).is_file() and (ROOT / key).stat().st_size > 0)
    print(
        f"Archive photo preflight: database_refs={len(references)} "
        f"manifest_matches={len(matched)} unmatched={mismatched} "
        f"already_on_oracle={already}", flush=True
    )
    if not args.write:
        return
    if not references or len(matched) < 0.90 * len(references):
        raise SystemExit("Drive manifest does not cover 90% of referenced archive photos")
    if args.limit:
        matched = matched[:args.limit]
    completed = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 6))) as pool:
        futures = {pool.submit(recover, key, sources[key]): key for key in matched}
        done = 0
        for f in concurrent.futures.as_completed(futures):
            status = f.result()
            completed[status] = completed.get(status, 0) + 1
            done += 1
            if done % 250 == 0:
                print(f"progress={done}/{len(matched)} restored={completed.get('restored',0)} "
                      f"existing={completed.get('existing',0)} failures={completed.get('failed',0)}",
                      flush=True)
    remaining = [
        key for key in references
        if not (ROOT / key).is_file() or (ROOT / key).stat().st_size == 0
    ]
    coverage = (len(references) - len(remaining)) / len(references)
    print(f"Recovery complete: archive_coverage={coverage:.2%} "
          f"pending={len(remaining)} statuses={completed}", flush=True)
    if args.limit:
        return
    if coverage < 0.95:
        raise SystemExit("Below 95% archive photo coverage; do NOT enable Oracle local media")
    print("Archive recovery passed; run independent private document checks before cutover")


if __name__ == "__main__":
    main()
