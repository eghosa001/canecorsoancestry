import os
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: render_wrangler.py INPUT OUTPUT")

hyperdrive_id = os.environ.get("CLOUDFLARE_HYPERDRIVE_ID", "").strip()
if not hyperdrive_id:
    raise SystemExit("CLOUDFLARE_HYPERDRIVE_ID is required.")

source = Path(sys.argv[1]).read_text(encoding="utf-8")
if "__HYPERDRIVE_ID__" not in source:
    raise SystemExit("wrangler template is missing the Hyperdrive placeholder.")

Path(sys.argv[2]).write_text(
    source.replace("__HYPERDRIVE_ID__", hyperdrive_id),
    encoding="utf-8",
)
