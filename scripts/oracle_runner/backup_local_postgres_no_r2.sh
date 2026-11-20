#!/usr/bin/env bash
# Emergency no-subscription encrypted backup on the existing Oracle VM.
# Same-VM backups are NOT offsite; mirror them to an independent free storage
# provider as soon as possible. Never replace the authoritative cca_live DB.
set -euo pipefail
umask 077
[[ "${GITHUB_REPOSITORY:-}" == "eghosa001/canecorsoancestry" &&
   "${GITHUB_REF:-}" == "refs/heads/main" &&
   "$(uname -m)" == "aarch64" &&
   "$(id -un)" == "opc" ]] || exit 2
sudo -n true
[[ "$(sudo -n cat /etc/cca/oracle-db-mode)" == local ]] || exit 2
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1 \
  -U cca_shadow_admin -d cca_live >/dev/null
readonly ROOT=/var/lib/cca/pgshadow/backup/oracle-local
sudo -n install -d -o root -g root -m 0700 "$ROOT"
# ROOT is root-only (0700): df without sudo fails with permission denied
# and previously made the disk check falsely report zero free space.
available_kib="$(sudo -n df -Pk "$ROOT" | awk 'END {print $4}')"
[[ "$available_kib" =~ ^[0-9]+$ && "$available_kib" -gt 4194304 ]] || {
  echo "::error::Insufficient verified free space for encrypted database backup"; exit 1;
}
echo "Oracle encrypted-backup preflight: free_KiB=$available_kib"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_id="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"
dump="$(mktemp "${RUNNER_TEMP:-/tmp}/cca-local-db-XXXXXXXX")"
sealed="$ROOT/cca-local-$stamp-$run_id.sealed"
restore="$ROOT/.cca-verify-$run_id.dump"
cleanup() {
  rm -f "$dump"
  sudo -n rm -f "$restore"
}
trap cleanup EXIT
# Dump only the authoritative Django schema, transactionally.
sudo -n podman exec cca-pg-shadow pg_dump -U cca_shadow_admin \
  -d cca_live -n django_app --format=custom --compress=6 > "$dump"
[[ -s "$dump" ]] || { echo "::error::Empty database dump"; exit 1; }
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py seal \
  "$dump" "$sealed" --secret-env /etc/cca/oracle-stage.env
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py open \
  "$sealed" "$restore" --secret-env /etc/cca/oracle-stage.env
original_sha="$(sha256sum "$dump" | cut -d' ' -f1)"
restored_sha="$(sudo -n sha256sum "$restore" | cut -d' ' -f1)"
[[ "$original_sha" == "$restored_sha" ]] || {
  echo "::error::Encrypted backup read-back checksum mismatch"; exit 1;
}
sudo -n rm -f "$restore"
sudo -n chmod 0600 "$sealed"
# Delete older *named* local archives only after a verified current snapshot.
sudo -n find "$ROOT" -maxdepth 1 -type f -name 'cca-local-*.sealed' -mtime +7 -delete
echo "PASS: encrypted local Oracle database snapshot verified (not offsite)."
echo "::warning::No independent offsite copy exists in this emergency backup mode."
