#!/usr/bin/env bash
# Protected Oracle Postgres backup. Hourly after local production switch.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(uname -m)" == "aarch64" &&
   "$(id -un)" == "opc" ]] || exit 2
sudo -n true
mode="$(sudo -n cat /etc/cca/oracle-db-mode 2>/dev/null || printf "supabase")"
if [[ "$mode" != local && "$GITHUB_EVENT_NAME" != push ]]; then
  echo "Oracle local DB not yet primary; scheduled backup skipped."
  exit 0
fi
[[ "$mode" == local || "$mode" == supabase ]] || exit 2
sudo -n podman container exists cca-pg-shadow
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1 -U cca_shadow_admin -d cca_shadow >/dev/null
readonly ROOT=/var/lib/cca/pgshadow/backup
sudo -n install -d -m 0700 "$ROOT"
image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
[[ "$image" == localhost/cca-oracle:* ]] || exit 2
db=cca_shadow
if [[ "$mode" == local ]]; then db=cca_live; fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
key="private-cca-postgres-backups/v1/$mode-$stamp-$GITHUB_RUN_ID.sealed"
dump="$RUNNER_TEMP/cca-postgres-$GITHUB_RUN_ID.dump"
sealed="$ROOT/hourly-$GITHUB_RUN_ID.sealed"
pointer="$ROOT/latest-$GITHUB_RUN_ID.json"
restore="$RUNNER_TEMP/cca-hourly-restore-$GITHUB_RUN_ID.dump"
cleanup() {
  rm -f "$dump" "$restore"
  sudo -n rm -f "$sealed" "$pointer"
}
trap cleanup EXIT
# pg_dump snapshots a consistent transaction, even during concurrent writes.
sudo -n podman exec cca-pg-shadow pg_dump \
  -U cca_shadow_admin -d "$db" -n django_app --format=custom --compress=6 \
  > "$dump"
test -s "$dump"
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py \
  seal "$dump" "$sealed" --secret-env /etc/cca/oracle-stage.env
[[ "$(sudo -n stat -c %s "$sealed")" -lt 78643200 ]] || {
  echo "::error::Backup exceeds encrypted R2 upload size limit"; exit 1;
}
uploader() {
  sudo -n podman run --rm --network host \
    --env-file /etc/cca/oracle-stage.env \
    --env PYTHONPATH=/app \
    -v "$ROOT:/backups:Z" \
    -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
    "$image" python /scripts/r2_postgres_backup.py "$@"
}
uploader upload --key "$key" --file "/backups/$(basename "$sealed")"
sudo -n python3 - "$pointer" "$key" "$sealed" "$mode" "$stamp" <<'PY'
import hashlib,json,sys
from pathlib import Path
output,key,path,mode,stamp=sys.argv[1:]
content={"format":"CCA-R2-DB-BACKUP-v1","mode":mode,"created_utc":stamp,
         "archive_key":key,"sha256":hashlib.sha256(Path(path).read_bytes()).hexdigest(),
         "encrypted":True,"schema":"django_app"}
f=Path(output)
f.write_text(json.dumps(content,separators=(",",":"))+"\n")
f.chmod(0o600)
PY
# Update the stable disaster-recovery pointer only AFTER the encrypted archive
# is re-downloaded and byte-for-byte verified by the upload helper.
uploader upload --key private-cca-postgres-backups/v1/latest.json \
  --file "/backups/$(basename "$pointer")"
sudo -n python3 - "$ROOT/backup-index.tsv" "$key" <<'PY'
import sys,time
from pathlib import Path
path=Path(sys.argv[1])
with path.open("a") as f:f.write(str(int(time.time()))+"\t"+sys.argv[2]+"\n")
path.chmod(0o600)
PY
echo "PASS: hourly encrypted offsite DB snapshot uploaded and latest recovery pointer verified."
echo "database_mode=$mode backup_key=$key"
# Seven-day retention; no deletion until newest backup is verified.
# Old keys are allowed only from the private root-owned index.
while IFS= read -r expired; do
  [[ -n "$expired" ]] || continue
  uploader delete --key "$expired" --file /dev/null
done < <(sudo -n python3 - "$ROOT/backup-index.tsv" <<'PY'
from pathlib import Path
import sys,time
cutoff=time.time()-7*86400
for line in Path(sys.argv[1]).read_text().splitlines():
    ts,sep,key=line.partition("\t")
    if sep and ts.isdigit() and int(ts)<cutoff:
        print(key)
PY
)
sudo -n python3 - "$ROOT/backup-index.tsv" <<'PY'
import os,sys,time
from pathlib import Path
p=Path(sys.argv[1]);cutoff=time.time()-7*86400
keep=[]
for line in p.read_text().splitlines():
    ts,sep,key=line.partition("\t")
    if sep and ts.isdigit() and int(ts)>=cutoff:keep.append(line)
tmp=p.with_suffix(".tmp")
tmp.write_text("\n".join(keep)+"\n");tmp.chmod(0o600);tmp.replace(p)
PY
