import json
import mimetypes
from pathlib import Path

SEED_PATH = Path("data/seeds/bellissimo-dogs.json")
KNOWN_MISSING_SOURCE_MEDIA = {
    "assets/dogs/himera-custodi-nos-main.avif",
    "assets/dogs/himera-custodi-nos-02.avif",
}


def media_entries(source_root, seed_path=SEED_PATH):
    source_root = Path(source_root)
    payload = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    entries = []
    missing = []

    for dog in payload.get("dogs", []):
        refs = []
        if dog.get("photo"):
            refs.append((dog["photo"], True, 0))

        sort_order = 1
        for field in ("gallery", "photoHistory"):
            for path in dog.get(field) or []:
                refs.append((path, False, sort_order))
                sort_order += 1

        for source_path, is_primary, order in refs:
            source_path = str(source_path).strip().replace("\\", "/")
            if not source_path.startswith("assets/") or ".." in Path(source_path).parts:
                raise ValueError(f"Unsafe Bellissimo media path: {source_path!r}")

            file_path = source_root / source_path
            if not file_path.is_file():
                missing.append(source_path)
                continue

            relative = source_path.removeprefix("assets/")
            object_key = f"bellissimo-geni/{relative}"
            entries.append(
                {
                    "dog_id": str(dog["id"]),
                    "source_path": source_path,
                    "file_path": str(file_path),
                    "object_key": object_key,
                    "is_primary": bool(is_primary),
                    "sort_order": order,
                    "content_type": (
                        mimetypes.guess_type(source_path)[0]
                        or "application/octet-stream"
                    ),
                }
            )

    unknown_missing = sorted(set(missing) - KNOWN_MISSING_SOURCE_MEDIA)
    if unknown_missing:
        raise ValueError(
            "Unexpected missing Bellissimo media: " + ", ".join(unknown_missing)
        )

    unique = {}
    for entry in entries:
        previous = unique.get(entry["object_key"])
        if previous and previous["source_path"] != entry["source_path"]:
            raise ValueError(f"R2 key collision: {entry['object_key']}")
        unique[entry["object_key"]] = entry

    return entries, sorted(set(missing)), list(unique.values())
