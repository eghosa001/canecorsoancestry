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
readonly RESTORE_CONTAINER="cca-restore-$GITHUB_RUN_ID"
sudo -n install -d -m 0700 "$TEMP"
cleanup() {
  sudo -n podman rm -f "$RESTORE_CONTAINER" >/dev/null 2>&1 || true
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
assert re.fullmatch(r"private-cca-postgres-backups/v1/local-[A-Za-z0-9_.-]+[.]sealed",key), "Invalid archive key"
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
# A decryptable but empty/schema-incomplete archive is not an acceptable
# restore candidate. Ensure the main canonical and audit tables are present.
sudo -n podman run --rm --network host \
  -v "$TEMP:/backups:ro,Z" docker.io/library/postgres:17 \
  pg_restore --list /backups/recovered.dump > "$RUNNER_TEMP/cca-restore-list-$GITHUB_RUN_ID.txt"
for table in registry_dog registry_dogimage registry_submission django_migrations; do
  if ! grep -Eq "TABLE DATA[[:space:]]+django_app[[:space:]]+${table}[[:space:]]" "$RUNNER_TEMP/cca-restore-list-$GITHUB_RUN_ID.txt"; then
    echo "::error::Encrypted archive lacks required table data: $table"
    rm -f "$RUNNER_TEMP/cca-restore-list-$GITHUB_RUN_ID.txt"
    exit 1
  fi
done
rm -f "$RUNNER_TEMP/cca-restore-list-$GITHUB_RUN_ID.txt"
# Actually restore to a new disposable PostgreSQL 17 instance. This is deliberately
# network-isolated, memory/CPU bounded and never connects to the live primary.
sudo -n podman run -d --name "$RESTORE_CONTAINER" --network none \
  --memory 768m --cpus 1 --pids-limit 128 \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$TEMP:/backups:ro,Z" \
  docker.io/library/postgres:17 >/dev/null
ready=0
for attempt in $(seq 1 30); do
  if sudo -n podman exec "$RESTORE_CONTAINER" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" = 1 || { echo "::error::Isolated PostgreSQL restore container did not start"; exit 1; }
# The live database keeps extension operator classes under 'extensions'.
# A schema-only pg_dump does not recreate extensions hosted outside django_app.
sudo -n podman exec "$RESTORE_CONTAINER" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE SCHEMA IF NOT EXISTS extensions;' >/dev/null
sudo -n podman exec "$RESTORE_CONTAINER" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;' >/dev/null
sudo -n podman exec "$RESTORE_CONTAINER" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;' >/dev/null
sudo -n podman exec -u 0 "$RESTORE_CONTAINER" pg_restore \
  --exit-on-error --no-owner --no-acl -U postgres -d postgres /backups/recovered.dump >/dev/null
restored_dogs="$(sudo -n podman exec "$RESTORE_CONTAINER" psql -U postgres -d postgres -Atqc \
  'SELECT COUNT(*) FROM django_app.registry_dog;')"
restored_migrations="$(sudo -n podman exec "$RESTORE_CONTAINER" psql -U postgres -d postgres -Atqc \
  'SELECT COUNT(*) FROM django_app.django_migrations;')"
[[ "$restored_dogs" =~ ^[0-9]+$ && "$restored_dogs" -ge 33000 ]] || {
  echo "::error::Isolated restore is missing expected canonical dog data"; exit 1;
}
[[ "$restored_migrations" =~ ^[0-9]+$ && "$restored_migrations" -gt 0 ]] || {
  echo "::error::Isolated restore is missing Django migration state"; exit 1;
}
echo "PASS: Encrypted R2 archive restored to independent PostgreSQL 17; $restored_dogs dogs and $restored_migrations migrations."
echo "Production database was not accessed for restore or modified."
