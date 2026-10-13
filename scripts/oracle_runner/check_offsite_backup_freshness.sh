#!/usr/bin/env bash
# Independent scheduled backup freshness watch. Read-only, never connects to live DB.
set -euo pipefail
umask 077
[[ "${GITHUB_REPOSITORY:-}" == "eghosa001/canecorsoancestry" &&
    "${GITHUB_REF:-}" == "refs/heads/main" &&
    "$(uname -m)" == "aarch64" &&
    "$(id -un)" == "opc" ]] || exit 2
test "$(sudo -n cat /etc/cca/oracle-db-mode)" = local
sudo -n test -s /etc/cca/oracle-stage.env
readonly DEST="/var/lib/cca/pgshadow/backup/freshness-${GITHUB_RUN_ID:?}.json"
cleanup() { sudo -n rm -f "$DEST"; }
trap cleanup EXIT
image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
[[ "$image" == localhost/cca-oracle:* ]] || exit 2
sudo -n podman run --rm --network host --env-file /etc/cca/oracle-stage.env \
  --env PYTHONPATH=/app \
  -v "$(dirname "$DEST"):/backups:Z" \
  -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
  "$image" python /scripts/r2_postgres_backup.py download \
  --key private-cca-postgres-backups/v1/latest.json \
  --file "/backups/$(basename "$DEST")"
sudo -n python3 - "$DEST" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p.get("format") == "CCA-R2-DB-BACKUP-v1"
assert p.get("mode") == "local", "Backup is not from Oracle's authoritative primary"
assert p.get("encrypted") is True
assert p.get("schema") == "django_app"
assert re.fullmatch(r"[0-9a-f]{64}", p.get("sha256", ""))
assert re.fullmatch(r"private-cca-postgres-backups/v1/local-[A-Za-z0-9_.-]+[.]sealed", p.get("archive_key", ""))
created = datetime.strptime(p["created_utc"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
age = (datetime.now(timezone.utc) - created).total_seconds()
assert -300 <= age <= 2.5 * 3600, f"FAIL: Offsite database backup is {age/3600:.2f} hours old"
print(f"PASS: Oracle offsite R2 encrypted backup pointer age={age/60:.0f}m, SHA256 present")
PY
