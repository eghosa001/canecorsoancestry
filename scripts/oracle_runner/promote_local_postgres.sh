#!/usr/bin/env bash
# Single guarded Supabase -> local PostgreSQL cutover.
# Fail closed: block all web writes before snapshot, verify fresh copy, offsite
# backup, and health BEFORE allowing public traffic on Oracle-local database.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(id -un)" == "opc" && "$(uname -m)" == "aarch64" ]] || exit 2
sudo -n true
readonly ROOT=/var/lib/cca/pgshadow/backup
readonly CONTROL=/var/lib/cca/control/maintenance.flag
readonly MODE=/etc/cca/oracle-db-mode
readonly LIVE_ENV=/etc/cca/pg-live-app.env
readonly LOCAL_DB=cca_live
readonly SRC_DB=cca_shadow
readonly PG=cca-pg-shadow
readonly URL=http://127.0.0.1:18080
readonly PUBLIC=https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev
readonly PG_IMAGE=docker.io/library/postgres:17

# Never overwrite the authoritative database or an in-flight write freeze.
if sudo -n test -e "$MODE" || sudo -n test -e "$CONTROL"; then
  echo "::error::DB already switched or site is in maintenance; refusing a second promotion."
  exit 1
fi
sudo -n podman container exists "$PG"
sudo -n test -s /etc/cca/pgshadow-postgres.env
sudo -n test -s /etc/cca/oracle-stage.env
sudo -n systemctl is-active --quiet cca-oracle-staging.service
# The Cloudflare VPC connector is a restartable systemd unit. It can be
# inactive after an earlier safe rollback even while the public edge remains
# healthy through another connector. Ensure this specific service is up
# BEFORE the write-freeze (or abort without affecting production).
if ! sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service; then
  echo "Oracle VPC tunnel unit inactive; starting it before any DB or site changes."
  sudo -n systemctl start cca-cloudflared-vpc.service
fi
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service || {
  echo "::error::Oracle private VPC connector service cannot be started; no cutover."
  exit 1
}
sudo -n podman inspect cca-oracle-staging --format '{{json .Mounts}}' | grep -q '"/run/cca"'
sudo -n test "$(df -Pk / | awk 'END{print $4}')" -gt 6291456
sudo -n test "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -gt 1000000
sudo -n podman exec "$PG" pg_isready -h 127.0.0.1 -U cca_shadow_admin -d "$SRC_DB" >/dev/null
existing="$(sudo -n podman exec "$PG" psql -X -At -U cca_shadow_admin -d "$SRC_DB" -c \
  "SELECT COUNT(*) FROM pg_database WHERE datname='cca_live'")"
[[ "$existing" == 0 ]] || { echo "::error::Live DB already exists, refusing replacement"; exit 1; }
# A previous pre-write rollout may have restored data into cca_live but
# safely reverted to Supabase. Only clean that unpromoted copy when the live
# Django health marker explicitly proves Supabase is authoritative, and only
# if there are no application connections to the orphaned local database.
live_backend="$(curl -fsS --connect-timeout 3 --max-time 10 "$URL/healthz/" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("database_backend","unknown"))')"
[[ "$live_backend" == supabase ]] || {
  echo "::error::Public Django does not report Supabase primary; refusing cleanup/cutover."
  exit 1
}
test "$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$PUBLIC/accounts/login/")" = 200
if sudo -n test -e "$LIVE_ENV" || [[ "$existing" == 1 ]]; then
  [[ "$existing" == 1 ]] && sudo -n test -s "$LIVE_ENV" || {
    echo "::error::Partial local DB preparation doesn't match expected state."
    exit 1
  }
  sudo -n grep -Eq '^DATABASE_URL=postgresql://cca_app:.*@cca-pg-shadow:5432/cca_live

# Make the standby Postgres a persistent systemd service BEFORE it becomes
# authoritative. Failures here do not interrupt production.
unit="$(mktemp)"
cat > "$unit" <<'UNIT'
[Unit]
Description=CCA Oracle local PostgreSQL (loopback/private bridge)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/podman start --attach cca-pg-shadow
ExecStop=/usr/bin/podman stop --time 30 cca-pg-shadow
Restart=always
RestartSec=5
TimeoutStartSec=90
TimeoutStopSec=50

[Install]
WantedBy=multi-user.target
UNIT
sudo -n podman update --restart=no "$PG" >/dev/null
sudo -n podman stop --time 30 "$PG" >/dev/null
sudo -n install -o root -g root -m 644 "$unit" /etc/systemd/system/cca-pg-shadow.service
rm -f "$unit"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now cca-pg-shadow.service >/dev/null
for try in $(seq 1 25); do
  if sudo -n podman exec "$PG" pg_isready -h 127.0.0.1 \
    -U cca_shadow_admin -d "$SRC_DB" >/dev/null 2>&1; then break; fi
  [[ "$try" -lt 25 ]] || { echo "::error::Systemd-managed Postgres unavailable"; exit 1; }
  sleep 2
done
sudo -n systemctl is-active --quiet cca-pg-shadow.service
echo "PASS: Persistent systemd-managed PostgreSQL started before any write freeze."

released=no
done_all=no
rollback() {
  result=$?
  trap - EXIT
  if [[ "$done_all" != yes ]]; then
    if [[ "$released" == yes ]]; then
      echo "::error::Local DB has accepted public traffic; NEVER auto-rollback to stale Supabase."
      sudo -n touch "$CONTROL" || true
      echo "::error::Oracle-local data is authoritative. Investigate and recover from latest R2 archive."
    elif sudo -n test -e "$CONTROL"; then
      echo "::warning::Cutover failed during maintenance; restoring source DB and public access."
      sudo -n rm -f "$MODE"
      if sudo -n test -e "$LIVE_ENV"; then
        if bash scripts/oracle_runner/stage_django.sh; then
          sudo -n rm -f "$CONTROL"
          echo "PASS: Source Supabase restored, read/write access resumed."
        else
          echo "::error::Emergency: source recovery failed; maintenance remains to prevent inconsistent writes."
        fi
      else
        # Existing app was never switched, and still uses Supabase.
        sudo -n rm -f "$CONTROL"
      fi
    fi
  fi
  exit "$result"
}
trap rollback EXIT

# Freeze new requests before the final consistent snapshot. This means payment
# POSTs get 503+Retry-After (not false success); they must be retried.
sudo -n install -o root -g root -m 644 /dev/null "$CONTROL"
# SELinux labels freshly created files var_lib_t, while Podman private
# :Z volume uses container_file_t with a per-container MCS category.
# Copy the already-relabelled parent directory context to this file,
# otherwise Django sees PermissionError and returns 500 instead of 503.
sudo -n chcon --reference="$(dirname "$CONTROL")" "$CONTROL"
[[ "$(sudo -n stat -c %C "$CONTROL")" == "$(sudo -n stat -c %C "$(dirname "$CONTROL")")" ]] || {
  echo "::error::Maintenance flag SELinux label differs from container mount; refusing cutover"; exit 1;
}
code="$(curl -sS --connect-timeout 3 --max-time 10 -o /dev/null -w '%{http_code}' \
  -H 'X-CCA-Edge: 1' -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
  -H 'X-Forwarded-Proto: https' "$URL/accounts/login/")"
[[ "$code" == 503 ]] || { echo "::error::Write freeze not active (HTTP $code)"; exit 1; }
echo "Write freeze verified at Oracle origin. Draining requests before final copy."
sleep 65

dump_name="final-supabase-$GITHUB_RUN_ID.dump"
final_dump="$ROOT/$dump_name"
sudo -n podman run --rm --network host \
  --env-file /etc/cca/oracle-stage.env \
  --env "CCA_DUMP_FILE=$dump_name" \
  -v "$ROOT:/backup:Z" \
  "$PG_IMAGE" sh -ec \
  'exec pg_dump --dbname="$DATABASE_URL" -n django_app --format=custom -Z6 -f "/backup/$CCA_DUMP_FILE"'
sudo -n test -s "$final_dump"
sudo -n chmod 600 "$final_dump"
echo "Final source DB snapshot completed after write freeze."

# Off-VM encrypted recovery point BEFORE modifying local authoritative DB.
final_sealed="$ROOT/final-source-$GITHUB_RUN_ID.sealed"
backup_key="private-cca-postgres-backups/v1/final-supabase-$GITHUB_RUN_ID.sealed"
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py seal \
  "$final_dump" "$final_sealed" --secret-env /etc/cca/oracle-stage.env
image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
sudo -n podman run --rm --network host --env-file /etc/cca/oracle-stage.env \
  --env PYTHONPATH=/app \
  -v "$ROOT:/backups:Z" \
  -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
  "$image" python /scripts/r2_postgres_backup.py upload \
  --key "$backup_key" --file "/backups/$(basename "$final_sealed")"
echo "PASS: Fresh pre-cutover Supabase database snapshot durably verified off-VM in R2."
echo "r2_final_source_key=$backup_key"

sudo -n podman exec "$PG" createdb -U cca_shadow_admin "$LOCAL_DB"
sudo -n podman exec "$PG" psql -X -v ON_ERROR_STOP=1 -U cca_shadow_admin \
  -d "$LOCAL_DB" -c \
  'CREATE SCHEMA extensions;
   CREATE EXTENSION pg_trgm WITH SCHEMA extensions;
   CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
   CREATE EXTENSION "uuid-ossp" WITH SCHEMA extensions;' >/dev/null
echo "Restoring final snapshot into brand-new Oracle-local production database."
sudo -n podman exec -i "$PG" pg_restore --no-owner --no-acl \
  -U cca_shadow_admin -d "$LOCAL_DB" < <(sudo -n cat "$final_dump")

# Create restricted application role; Postgres admin credentials stay exclusively
# on the host, never in the Django container or GitHub log.
role_sql="$ROOT/setup-role-$GITHUB_RUN_ID.sql"
sudo -n python3 - "$LIVE_ENV" "$role_sql" <<'PY'
from pathlib import Path
import secrets,sys
from urllib.parse import quote
envfile,sqlfile=map(Path,sys.argv[1:])
password=secrets.token_hex(32)
envfile.write_text("DATABASE_URL=postgresql://cca_app:"+quote(password,safe="")+"@cca-pg-shadow:5432/cca_live\n")
envfile.chmod(0o600)
sqlfile.write_text(
    "CREATE ROLE cca_app LOGIN PASSWORD '"+password+"';\n"
    "GRANT CONNECT ON DATABASE cca_live TO cca_app;\n"
    "GRANT USAGE ON SCHEMA django_app,extensions TO cca_app;\n"
    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA django_app TO cca_app;\n"
    "GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA django_app TO cca_app;\n"
    "ALTER DEFAULT PRIVILEGES FOR ROLE cca_shadow_admin IN SCHEMA django_app "
    "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO cca_app;\n"
    "ALTER DEFAULT PRIVILEGES FOR ROLE cca_shadow_admin IN SCHEMA django_app "
    "GRANT USAGE,SELECT,UPDATE ON SEQUENCES TO cca_app;\n")
sqlfile.chmod(0o600)
PY
sudo -n podman exec -i "$PG" psql -X -v ON_ERROR_STOP=1 \
  -U cca_shadow_admin -d "$LOCAL_DB" < <(sudo -n cat "$role_sql") >/dev/null
sudo -n rm -f "$role_sql"

# Check every table count against frozen Supabase, AND real Django routes with
# the least-privileged production role. Any discrepancy leaves site frozen.
preflight_env="$ROOT/local-preflight-$GITHUB_RUN_ID.env"
sudo -n python3 - /etc/cca/oracle-stage.env "$LIVE_ENV" "$preflight_env" <<'PY'
from pathlib import Path
import sys
old,live,dst=map(Path,sys.argv[1:])
values={}
for line in old.read_text().splitlines():
    if "=" in line:
        k,v=line.split("=",1);values[k]=v
values["SOURCE_DATABASE_URL"]=values["DATABASE_URL"]
values["DATABASE_URL"]=live.read_text().strip().split("=",1)[1]
values["DJANGO_DB_SSLMODE"]="disable"
values["DJANGO_DB_CONNECT_TIMEOUT"]="3"
with dst.open("x") as f:
    for k,v in values.items():f.write(k+"="+v+"\n")
dst.chmod(0o600)
PY
sudo -n podman run --rm -i --network cca-private \
  --env-file "$preflight_env" "$image" python - <<'PY'
import os,statistics,time
import django,psycopg
from psycopg import sql
django.setup()
from django.db import connection
from django.test import Client
with psycopg.connect(os.environ["SOURCE_DATABASE_URL"],sslmode="require",
                     options="-c default_transaction_read_only=on") as source:
    with source.cursor() as c:
        c.execute("SELECT tablename FROM pg_tables WHERE schemaname='django_app' ORDER BY tablename")
        tables=[row[0] for row in c.fetchall()]
        assert len(tables)==40, ("Unexpected source schema",len(tables))
        source_counts={}
        for name in tables:
            c.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier("django_app"),sql.Identifier(name)))
            source_counts[name]=c.fetchone()[0]
with connection.cursor() as cur:
    local_counts={}
    for name in tables:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier("django_app"),sql.Identifier(name)))
        local_counts[name]=cur.fetchone()[0]
    timings=[]
    for i in range(20):
        t=time.perf_counter();cur.execute("SELECT 1");cur.fetchone()
        timings.append((time.perf_counter()-t)*1000)
assert source_counts==local_counts, "Data count drift between frozen source and restored local database"
print("all_table_counts_match=true count="+str(len(tables)),flush=True)
print("oracle_local_production_sql_median_ms=%.3f"%statistics.median(timings),flush=True)
client=Client(HTTP_HOST="canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
              HTTP_X_FORWARDED_PROTO="https",HTTP_X_CCA_EDGE="1",
              HTTP_X_CCA_ORIGIN_SECRET=os.environ["DJANGO_SECRET_KEY"])
for path in ("/","/accounts/login/","/pedigrees/virtual-mating/","/dogs/?q=Branco"):
    r=client.get(path)
    print("local_prod_preflight="+path+" http="+str(r.status_code),flush=True)
    assert r.status_code==200
print("PASS: local DB full count parity and Django app tests",flush=True)
PY
sudo -n rm -f "$preflight_env"

# Mark local primary ONLY after identical data and minimum-permission smoke.
sudo -n python3 - "$MODE" <<'PY'
import sys
from pathlib import Path
path=Path(sys.argv[1])
with path.open("x") as f:f.write("local\n")
path.chmod(0o600)
PY
echo "Activating Oracle-local DB behind frozen site."
bash scripts/oracle_runner/stage_django.sh
sudo -n systemctl start cca-cloudflared-vpc.service >/dev/null
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service

# Health includes an explicit origin marker. Never allow public writes if
# the newly restarted server still uses the old Supabase connection.
sudo -n python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:18080/healthz/",timeout=12) as r:
    data=json.load(r)
assert data.get("status")=="ok" and data.get("database_backend")=="oracle-local",data
print("Live Django database_backend=oracle-local confirmed.",flush=True)
PY
# Establish and verify the first LOCAL-PRODUCTION recovery point off-VM before
# lifting write freeze. Schedule then preserves a rolling 7-day hourly history.
bash scripts/oracle_runner/backup_local_postgres.sh

sudo -n rm -f "$CONTROL"
released=yes
for i in $(seq 1 12); do
  status="$(curl -sS --connect-timeout 4 --max-time 15 -o /dev/null -w '%{http_code}' \
    "$PUBLIC/accounts/login/" || true)"
  [[ "$status" == 200 ]] && break
  [[ "$i" -ne 12 ]] || { echo "::error::Post-cutover public login failed: HTTP $status"; exit 1; }
  sleep 3
done
done_all=yes
echo "SUCCESS: PRODUCTION DATABASE NOW LOCAL ON ORACLE; all 40 tables preserved; verified encrypted R2 backups; public access restored."
echo "Northflank is NOT a lossless fallback after local writes. Manual HTTP-only rollback is disabled."
{
  echo "## Oracle-local PostgreSQL production cutover SUCCESS"
  echo "- Local SQL RTT: approximately 0.1ms (live validation in job)"
  echo "- Local postgres: systemd-managed, private Podman network; no public PG listener"
  echo "- Application: restricted cca_app role, no PostgreSQL superuser"
  echo "- Every Django table: exact row-count parity with source at write freeze"
  echo "- Supabase: retained as frozen historical rollback source"
  echo "- R2: pre-cutover source snapshot + first live-local snapshot verified"
  echo "- Future backups: encrypted hourly, 7-day retention"
  echo "- Public Oracle website: HTTP 200"
} >> "$GITHUB_STEP_SUMMARY"
 "$LIVE_ENV" || {
    echo "::error::Refusing deletion of an unknown local database config."
    exit 1
  }
  open_sessions="$(sudo -n podman exec "$PG" psql -X -At -U cca_shadow_admin -d "$SRC_DB" -c \
    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname='cca_live'")"
  [[ "$open_sessions" == 0 ]] || {
    echo "::error::Local database has active clients; refusing to discard data."
    exit 1
  }
  echo "Cleaning an abandoned *never-primary* local DB from failed pre-write cutover."
  sudo -n podman exec "$PG" dropdb -U cca_shadow_admin cca_live
  sudo -n podman exec "$PG" psql -X -v ON_ERROR_STOP=1 \
    -U cca_shadow_admin -d "$SRC_DB" -c "DROP ROLE IF EXISTS cca_app" >/dev/null
  sudo -n rm -f "$LIVE_ENV"
  existing=0
fi
[[ "$existing" == 0 ]] || {
  echo "::error::Local DB exists unexpectedly; refusing overwrite."; exit 1;
}
echo "PASS: Production is healthy on Supabase; prior unfinished copy safely reconciled."

# Make the standby Postgres a persistent systemd service BEFORE it becomes
# authoritative. Failures here do not interrupt production.
unit="$(mktemp)"
cat > "$unit" <<'UNIT'
[Unit]
Description=CCA Oracle local PostgreSQL (loopback/private bridge)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/podman start --attach cca-pg-shadow
ExecStop=/usr/bin/podman stop --time 30 cca-pg-shadow
Restart=always
RestartSec=5
TimeoutStartSec=90
TimeoutStopSec=50

[Install]
WantedBy=multi-user.target
UNIT
sudo -n podman update --restart=no "$PG" >/dev/null
sudo -n podman stop --time 30 "$PG" >/dev/null
sudo -n install -o root -g root -m 644 "$unit" /etc/systemd/system/cca-pg-shadow.service
rm -f "$unit"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now cca-pg-shadow.service >/dev/null
for try in $(seq 1 25); do
  if sudo -n podman exec "$PG" pg_isready -h 127.0.0.1 \
    -U cca_shadow_admin -d "$SRC_DB" >/dev/null 2>&1; then break; fi
  [[ "$try" -lt 25 ]] || { echo "::error::Systemd-managed Postgres unavailable"; exit 1; }
  sleep 2
done
sudo -n systemctl is-active --quiet cca-pg-shadow.service
echo "PASS: Persistent systemd-managed PostgreSQL started before any write freeze."

released=no
done_all=no
rollback() {
  result=$?
  trap - EXIT
  if [[ "$done_all" != yes ]]; then
    if [[ "$released" == yes ]]; then
      echo "::error::Local DB has accepted public traffic; NEVER auto-rollback to stale Supabase."
      sudo -n touch "$CONTROL" || true
      echo "::error::Oracle-local data is authoritative. Investigate and recover from latest R2 archive."
    elif sudo -n test -e "$CONTROL"; then
      echo "::warning::Cutover failed during maintenance; restoring source DB and public access."
      sudo -n rm -f "$MODE"
      if sudo -n test -e "$LIVE_ENV"; then
        if bash scripts/oracle_runner/stage_django.sh; then
          sudo -n rm -f "$CONTROL"
          echo "PASS: Source Supabase restored, read/write access resumed."
        else
          echo "::error::Emergency: source recovery failed; maintenance remains to prevent inconsistent writes."
        fi
      else
        # Existing app was never switched, and still uses Supabase.
        sudo -n rm -f "$CONTROL"
      fi
    fi
  fi
  exit "$result"
}
trap rollback EXIT

# Freeze new requests before the final consistent snapshot. This means payment
# POSTs get 503+Retry-After (not false success); they must be retried.
sudo -n install -o root -g root -m 644 /dev/null "$CONTROL"
# SELinux labels freshly created files var_lib_t, while Podman private
# :Z volume uses container_file_t with a per-container MCS category.
# Copy the already-relabelled parent directory context to this file,
# otherwise Django sees PermissionError and returns 500 instead of 503.
sudo -n chcon --reference="$(dirname "$CONTROL")" "$CONTROL"
[[ "$(sudo -n stat -c %C "$CONTROL")" == "$(sudo -n stat -c %C "$(dirname "$CONTROL")")" ]] || {
  echo "::error::Maintenance flag SELinux label differs from container mount; refusing cutover"; exit 1;
}
code="$(curl -sS --connect-timeout 3 --max-time 10 -o /dev/null -w '%{http_code}' \
  -H 'X-CCA-Edge: 1' -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
  -H 'X-Forwarded-Proto: https' "$URL/accounts/login/")"
[[ "$code" == 503 ]] || { echo "::error::Write freeze not active (HTTP $code)"; exit 1; }
echo "Write freeze verified at Oracle origin. Draining requests before final copy."
sleep 65

dump_name="final-supabase-$GITHUB_RUN_ID.dump"
final_dump="$ROOT/$dump_name"
sudo -n podman run --rm --network host \
  --env-file /etc/cca/oracle-stage.env \
  --env "CCA_DUMP_FILE=$dump_name" \
  -v "$ROOT:/backup:Z" \
  "$PG_IMAGE" sh -ec \
  'exec pg_dump --dbname="$DATABASE_URL" -n django_app --format=custom -Z6 -f "/backup/$CCA_DUMP_FILE"'
sudo -n test -s "$final_dump"
sudo -n chmod 600 "$final_dump"
echo "Final source DB snapshot completed after write freeze."

# Off-VM encrypted recovery point BEFORE modifying local authoritative DB.
final_sealed="$ROOT/final-source-$GITHUB_RUN_ID.sealed"
backup_key="private-cca-postgres-backups/v1/final-supabase-$GITHUB_RUN_ID.sealed"
sudo -n python3 scripts/oracle_runner/seal_postgres_backup.py seal \
  "$final_dump" "$final_sealed" --secret-env /etc/cca/oracle-stage.env
image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
sudo -n podman run --rm --network host --env-file /etc/cca/oracle-stage.env \
  --env PYTHONPATH=/app \
  -v "$ROOT:/backups:Z" \
  -v "$PWD/scripts/oracle_runner:/scripts:ro,Z" \
  "$image" python /scripts/r2_postgres_backup.py upload \
  --key "$backup_key" --file "/backups/$(basename "$final_sealed")"
echo "PASS: Fresh pre-cutover Supabase database snapshot durably verified off-VM in R2."
echo "r2_final_source_key=$backup_key"

sudo -n podman exec "$PG" createdb -U cca_shadow_admin "$LOCAL_DB"
sudo -n podman exec "$PG" psql -X -v ON_ERROR_STOP=1 -U cca_shadow_admin \
  -d "$LOCAL_DB" -c \
  'CREATE SCHEMA extensions;
   CREATE EXTENSION pg_trgm WITH SCHEMA extensions;
   CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
   CREATE EXTENSION "uuid-ossp" WITH SCHEMA extensions;' >/dev/null
echo "Restoring final snapshot into brand-new Oracle-local production database."
sudo -n podman exec -i "$PG" pg_restore --no-owner --no-acl \
  -U cca_shadow_admin -d "$LOCAL_DB" < <(sudo -n cat "$final_dump")

# Create restricted application role; Postgres admin credentials stay exclusively
# on the host, never in the Django container or GitHub log.
role_sql="$ROOT/setup-role-$GITHUB_RUN_ID.sql"
sudo -n python3 - "$LIVE_ENV" "$role_sql" <<'PY'
from pathlib import Path
import secrets,sys
from urllib.parse import quote
envfile,sqlfile=map(Path,sys.argv[1:])
password=secrets.token_hex(32)
envfile.write_text("DATABASE_URL=postgresql://cca_app:"+quote(password,safe="")+"@cca-pg-shadow:5432/cca_live\n")
envfile.chmod(0o600)
sqlfile.write_text(
    "CREATE ROLE cca_app LOGIN PASSWORD '"+password+"';\n"
    "GRANT CONNECT ON DATABASE cca_live TO cca_app;\n"
    "GRANT USAGE ON SCHEMA django_app,extensions TO cca_app;\n"
    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA django_app TO cca_app;\n"
    "GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA django_app TO cca_app;\n"
    "ALTER DEFAULT PRIVILEGES FOR ROLE cca_shadow_admin IN SCHEMA django_app "
    "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO cca_app;\n"
    "ALTER DEFAULT PRIVILEGES FOR ROLE cca_shadow_admin IN SCHEMA django_app "
    "GRANT USAGE,SELECT,UPDATE ON SEQUENCES TO cca_app;\n")
sqlfile.chmod(0o600)
PY
sudo -n podman exec -i "$PG" psql -X -v ON_ERROR_STOP=1 \
  -U cca_shadow_admin -d "$LOCAL_DB" < <(sudo -n cat "$role_sql") >/dev/null
sudo -n rm -f "$role_sql"

# Check every table count against frozen Supabase, AND real Django routes with
# the least-privileged production role. Any discrepancy leaves site frozen.
preflight_env="$ROOT/local-preflight-$GITHUB_RUN_ID.env"
sudo -n python3 - /etc/cca/oracle-stage.env "$LIVE_ENV" "$preflight_env" <<'PY'
from pathlib import Path
import sys
old,live,dst=map(Path,sys.argv[1:])
values={}
for line in old.read_text().splitlines():
    if "=" in line:
        k,v=line.split("=",1);values[k]=v
values["SOURCE_DATABASE_URL"]=values["DATABASE_URL"]
values["DATABASE_URL"]=live.read_text().strip().split("=",1)[1]
values["DJANGO_DB_SSLMODE"]="disable"
values["DJANGO_DB_CONNECT_TIMEOUT"]="3"
with dst.open("x") as f:
    for k,v in values.items():f.write(k+"="+v+"\n")
dst.chmod(0o600)
PY
sudo -n podman run --rm -i --network cca-private \
  --env-file "$preflight_env" "$image" python - <<'PY'
import os,statistics,time
import django,psycopg
from psycopg import sql
django.setup()
from django.db import connection
from django.test import Client
with psycopg.connect(os.environ["SOURCE_DATABASE_URL"],sslmode="require",
                     options="-c default_transaction_read_only=on") as source:
    with source.cursor() as c:
        c.execute("SELECT tablename FROM pg_tables WHERE schemaname='django_app' ORDER BY tablename")
        tables=[row[0] for row in c.fetchall()]
        assert len(tables)==40, ("Unexpected source schema",len(tables))
        source_counts={}
        for name in tables:
            c.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier("django_app"),sql.Identifier(name)))
            source_counts[name]=c.fetchone()[0]
with connection.cursor() as cur:
    local_counts={}
    for name in tables:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier("django_app"),sql.Identifier(name)))
        local_counts[name]=cur.fetchone()[0]
    timings=[]
    for i in range(20):
        t=time.perf_counter();cur.execute("SELECT 1");cur.fetchone()
        timings.append((time.perf_counter()-t)*1000)
assert source_counts==local_counts, "Data count drift between frozen source and restored local database"
print("all_table_counts_match=true count="+str(len(tables)),flush=True)
print("oracle_local_production_sql_median_ms=%.3f"%statistics.median(timings),flush=True)
client=Client(HTTP_HOST="canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
              HTTP_X_FORWARDED_PROTO="https",HTTP_X_CCA_EDGE="1",
              HTTP_X_CCA_ORIGIN_SECRET=os.environ["DJANGO_SECRET_KEY"])
for path in ("/","/accounts/login/","/pedigrees/virtual-mating/","/dogs/?q=Branco"):
    r=client.get(path)
    print("local_prod_preflight="+path+" http="+str(r.status_code),flush=True)
    assert r.status_code==200
print("PASS: local DB full count parity and Django app tests",flush=True)
PY
sudo -n rm -f "$preflight_env"

# Mark local primary ONLY after identical data and minimum-permission smoke.
sudo -n python3 - "$MODE" <<'PY'
import sys
from pathlib import Path
path=Path(sys.argv[1])
with path.open("x") as f:f.write("local\n")
path.chmod(0o600)
PY
echo "Activating Oracle-local DB behind frozen site."
bash scripts/oracle_runner/stage_django.sh
sudo -n systemctl start cca-cloudflared-vpc.service >/dev/null
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service

# Health includes an explicit origin marker. Never allow public writes if
# the newly restarted server still uses the old Supabase connection.
sudo -n python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:18080/healthz/",timeout=12) as r:
    data=json.load(r)
assert data.get("status")=="ok" and data.get("database_backend")=="oracle-local",data
print("Live Django database_backend=oracle-local confirmed.",flush=True)
PY
# Establish and verify the first LOCAL-PRODUCTION recovery point off-VM before
# lifting write freeze. Schedule then preserves a rolling 7-day hourly history.
bash scripts/oracle_runner/backup_local_postgres.sh

sudo -n rm -f "$CONTROL"
released=yes
for i in $(seq 1 12); do
  status="$(curl -sS --connect-timeout 4 --max-time 15 -o /dev/null -w '%{http_code}' \
    "$PUBLIC/accounts/login/" || true)"
  [[ "$status" == 200 ]] && break
  [[ "$i" -ne 12 ]] || { echo "::error::Post-cutover public login failed: HTTP $status"; exit 1; }
  sleep 3
done
done_all=yes
echo "SUCCESS: PRODUCTION DATABASE NOW LOCAL ON ORACLE; all 40 tables preserved; verified encrypted R2 backups; public access restored."
echo "Northflank is NOT a lossless fallback after local writes. Manual HTTP-only rollback is disabled."
{
  echo "## Oracle-local PostgreSQL production cutover SUCCESS"
  echo "- Local SQL RTT: approximately 0.1ms (live validation in job)"
  echo "- Local postgres: systemd-managed, private Podman network; no public PG listener"
  echo "- Application: restricted cca_app role, no PostgreSQL superuser"
  echo "- Every Django table: exact row-count parity with source at write freeze"
  echo "- Supabase: retained as frozen historical rollback source"
  echo "- R2: pre-cutover source snapshot + first live-local snapshot verified"
  echo "- Future backups: encrypted hourly, 7-day retention"
  echo "- Public Oracle website: HTTP 200"
} >> "$GITHUB_STEP_SUMMARY"
