#!/usr/bin/env python3
"""Build an exact public-archive Drive lookup for signed photo fallback.

The map is bundled into the Cloudflare media Worker at deploy time; no
private dog images, documents, or user uploads are included.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/canecorso_drive_manifest_v1/index.json"
OUT = ROOT / "src/drive-archive-map.js"
ID_PATTERN = re.compile(r"^(\d+)(?:_|\.)")
EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png", ".avif"}


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    result = {}
    selected = {}
    for segment in index["segments"]:
        path = ROOT / segment["path"]
        seen = 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            seen += 1
            item = json.loads(raw)
            filename = Path(item["path"]).name
            match = ID_PATTERN.match(filename)
            ext = Path(filename).suffix.lower()
            if not match or ext not in EXTENSIONS:
                continue
            source_id = str(int(match.group(1)))
            key = f"dogs/archive/{int(source_id) // 1000:03d}/{source_id}{ext}"
            score = int(item.get("size") or 0)
            if score < 100 or score > 12 * 1024 * 1024:
                continue
            if key not in selected or score > selected[key]:
                selected[key] = score
                result[key] = str(item["id"])
        if seen != int(segment["count"]):
            raise SystemExit(f"Manifest segment incomplete: {path}")
    if len(result) < 14000:
        raise SystemExit(f"Refusing to generate partial archive map: {len(result)} entries")
    keys = dict(sorted(result.items()))
    OUT.write_text(
        "// GENERATED from the owner's already-public Drive dog archive; no private uploads.\n"
        "export const driveArchiveIds = Object.freeze("
        + json.dumps(keys, separators=(",", ":"), ensure_ascii=True)
        + ");\n", encoding="utf-8"
    )
    print(f"Public archive fallback: {len(keys)} verified manifest key matches; "
          f"bundle bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
