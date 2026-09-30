from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "staticfiles"
target_root = ROOT / "worker_assets"
target = target_root / "static"

if target_root.exists():
    shutil.rmtree(target_root)
target.mkdir(parents=True)

if not source.exists():
    raise SystemExit("staticfiles/ does not exist; run collectstatic first.")

for item in source.iterdir():
    destination = target / item.name
    if item.is_dir():
        shutil.copytree(item, destination)
    else:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)

print(f"Prepared Worker assets in {target_root}")
