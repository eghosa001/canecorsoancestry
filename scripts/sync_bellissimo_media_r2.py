import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

from registry.bellissimo_media import SEED_PATH, media_entries


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root")
    parser.add_argument("--bucket", default="canecorsoancestry-media")
    args = parser.parse_args()

    source_root = Path(args.source_root)
    source_seed = source_root / "data" / "dogs.json"
    if not source_seed.is_file():
        raise SystemExit(f"Bellissimo source dataset not found: {source_seed}")
    if source_seed.read_bytes() != SEED_PATH.read_bytes():
        raise SystemExit(
            "Bellissimo source data differs from the verified ancestry snapshot. "
            "Refresh and review the snapshot before uploading media."
        )

    entries, missing, unique = media_entries(source_root)

    with tempfile.TemporaryDirectory() as temp_dir:
        verify_dir = Path(temp_dir)
        for entry in unique:
            file_path = Path(entry["file_path"])
            object_path = f"{args.bucket}/{entry['object_key']}"
            run(
                "npx",
                "wrangler",
                "r2",
                "object",
                "put",
                object_path,
                f"--file={file_path}",
                f"--content-type={entry['content_type']}",
                "--remote",
            )

            downloaded = verify_dir / file_path.name
            run(
                "npx",
                "wrangler",
                "r2",
                "object",
                "get",
                object_path,
                f"--file={downloaded}",
                "--remote",
            )
            if digest(file_path) != digest(downloaded):
                raise SystemExit(f"R2 verification failed for {entry['object_key']}")

    print(
        f"Verified {len(unique)} R2 objects for {len(set(e['dog_id'] for e in entries))} dogs. "
        f"Known missing source files: {len(missing)}."
    )
    for path in missing:
        print(f"KNOWN_MISSING: {path}")


if __name__ == "__main__":
    main()
