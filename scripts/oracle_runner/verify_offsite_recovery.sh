#!/usr/bin/env bash
# Read-only Oracle-primary recovery integrity test. Never touches a live DB.
set -euo pipefail
umask 077

[[ "${GITHUB_REPOSITORY:-}" == "eghosa001/canecorsoancestry" &&
    "${GITHUB_REF:-}" == "refs/heads/main" &&
    "$(uname -m)" == "aarch64" &&
    "$(id -un)" == "opc" ]] || exit 2
sudo -n true
test "$(sudo -n cat /etc/cca/oracle-db-mode)" = local
sudo -n systemctl is-active --quiet cca-pg-shadow.service
sudo -n test -s /etc/cca/oracle-stage.env

readonly ROOT="/var/lib/cca/pgshadow/backup"
readonly TEMP="$ROOT/recovery-drill-${GITHUB_RUN_ID:?}"
readonly INDEX="$TEMP/latest.json"
readonly SEALED="$TEMP/latest.sealed"
readonly DUMP="$TEMP/recovered.dump"
sudo -n install -d -m 0700 "$TEMP"
cleanup() {
  sudo -n rm -f "$INDEX" "$SEALED" "$DUMP"
  sudo -n rmdir "$TEMP" || true
}
trap cleanup EXIT

image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
[[ "$image" == localhost/cca-oracle:* ]] || exit 2
storage() {
  sudo -n podman run --rm --network host \
    --env-file /etc/cca/oracle-stage.env \
    --env PYTHONPATH=/app \
    -v "$TEMP:/backups:Z" \
    -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
    "$image" python /scripts/r2_postgres_backup.py "$@"
}
storage download --key private-cca-postgres-backups/v1/latest.json --file /backups/latest.json

# Parse and validate the pointer before requesting the archive from R2.
# Never execute values from a remote JSON document as shell commands.
read -r key expected_sha < <(sudo -n python3 - "$INDEX" <<'PY'
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
assert p.get("format")=="CCA-R2-DB-BACKUP-v1"
assert p.get("mode")=="local", "Backup pointer is not from Oracle primary"
assert p.get("encrypted") is True and p.get("schema")=="django_app"
key=p.get("archive_key","")
sha=p.get("sha256","")
assert re.fullmatch(r"private-cca-postgres-backups/v1/local-[A-Za-z0-9_.-]+\\.sealed",key), "Invalid archive key"
assert re.fullmatch(r"[0-9a-f]{64}",sha), "Invalid checksum"
age=(datetime.now(timezone.utc)-datetime.strptime(p["created_utc"],"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)).total_seconds()
assert -300 < age < 4*3600, "Most recent offsite backup is older than four hours"
print(key,sha)
PY
)
test -n "$key" && test -n "$expected_sha"
storage download --key "$key" --file /backups/latest.sealed
actual_sha="$(sudo -n sha256sum "$SEALED" | cut -d' ' -f1)"
test "$actual_sha" = "$expected_sha" || {
  echo "::error::Offsite PostgreSQL archive checksum mismatch"; exit 1;
}
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py open "$SEALED" "$DUMP" \
  --secret-env /etc/cca/oracle-stage.env
sudo -n podman run --rm --network host \
  -v "$TEMP:/backups:ro,Z" docker.io/library/postgres:17 \
  pg_restore --list /backups/recovered.dump > /dev/null
echo "PASS: Oracle-primary R2 archive downloaded, SHA256 verified, authenticated, decrypted and parsed with pg_restore."
echo "Read-only recovery integrity check; no production tables or services modified."
