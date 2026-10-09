#!/usr/bin/env bash
# Validate encrypted off-VM database snapshot before any local DB cutover.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(uname -m)" == "aarch64" && "$(id -un)" == "opc" ]] || exit 2
sudo -n true
readonly ROOT="/var/lib/cca/pgshadow/backup"
readonly SOURCE="$ROOT/source.dump"
sudo -n test -s "$SOURCE"
sudo -n test -f /etc/cca/oracle-stage.env
sudo -n systemctl is-active --quiet cca-oracle-staging.service
command -v openssl >/dev/null
app_image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
[[ "$app_image" == localhost/cca-oracle:* ]] || exit 2
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
shortsha="$(printf %.12s "$GITHUB_SHA")"
key="private-cca-postgres-backups/v1/source-$stamp-$shortsha.sealed"
sealed="$ROOT/r2-source-$GITHUB_RUN_ID.sealed"
returned="$ROOT/r2-probe-$GITHUB_RUN_ID.sealed"
restored="$ROOT/r2-restored-$GITHUB_RUN_ID.dump"
cleanup() { sudo -n rm -f "$returned" "$restored"; }
trap cleanup EXIT
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py seal "$SOURCE" "$sealed" \
  --secret-env /etc/cca/oracle-stage.env
[[ "$(sudo -n stat -c %s "$sealed")" -lt 78643200 ]] || {
 echo "::error::Encrypted dump too large for R2 Worker upload"; exit 1;
}
sudo -n podman run --rm --network host \
  --env-file /etc/cca/oracle-stage.env \
  --env PYTHONPATH=/app \
  -v "$ROOT:/backups:Z" \
  -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
  "$app_image" python /scripts/r2_postgres_backup.py \
  upload --key "$key" --file "/backups/$(basename "$sealed")"
sudo -n podman run --rm --network host \
  --env-file /etc/cca/oracle-stage.env \
  --env PYTHONPATH=/app \
  -v "$ROOT:/backups:Z" \
  -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
  "$app_image" python /scripts/r2_postgres_backup.py \
  download --key "$key" --file "/backups/$(basename "$returned")"
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py open "$returned" "$restored" \
  --secret-env /etc/cca/oracle-stage.env
original_sha="$(sudo -n sha256sum "$SOURCE" | cut -d' ' -f1)"
restored_sha="$(sudo -n sha256sum "$restored" | cut -d' ' -f1)"
[[ "$original_sha" == "$restored_sha" ]] || {
 echo "::error::Off-VM backup returned non-identical database dump"; exit 1;
}
sudo -n podman run --rm --network host \
  -v "$ROOT:/backups:Z" docker.io/library/postgres:17 \
  pg_restore --list "/backups/$(basename "$restored")" >/dev/null
echo "PASS: encrypted R2 backup uploaded, downloaded, authenticated, decrypted, and verified as a valid PostgreSQL archive."
echo "backup_r2_key=$key"
echo "source_archive_sha256=$original_sha"
echo "Production remains Supabase."
