#!/usr/bin/env bash
# Pre-cutover trial only. Never changes live Django/database/Cloudflare routing.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(uname -m)" == "aarch64" &&
   "$(id -un)" == "opc" ]] || { echo "::error::Wrong runner/ref"; exit 1; }
sudo -n true
readonly PG_IMAGE="docker.io/library/postgres:17"
readonly DB_NAME="cca_shadow"
readonly DB_CONTAINER="cca-pg-shadow"
readonly ROOT="/var/lib/cca/pgshadow"
readonly PG_ENV="/etc/cca/pgshadow-postgres.env"
readonly DJANGO_ENV="/etc/cca/pgshadow-django.env"
readonly APP_CONTAINER="cca-oracle-staging"
[[ "$(df -Pk / | awk 'END{print $4}')" -gt 6291456 ]] || {
  echo "::error::Not enough free disk for local DB trial"; exit 1;
}
[[ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -gt 1500000 ]] || {
  echo "::error::Not enough available memory"; exit 1;
}
sudo -n systemctl is-active --quiet cca-oracle-staging.service
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service
curl -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:18080/healthz/ >/dev/null
[[ ! -e "$PG_ENV" && ! -e "$DJANGO_ENV" ]] || {
  echo "::error::Trial already provisioned; refusing to overwrite secrets or snapshot"; exit 1;
}
if sudo -n podman container exists "$DB_CONTAINER"; then
  echo "::error::Shadow Postgres container already exists"; exit 1;
fi
sudo -n install -d -m 0700 /etc/cca "$ROOT" "$ROOT/data" "$ROOT/backup"
sudo -n python3 - "$PG_ENV" <<'PY'
import secrets,sys
from pathlib import Path
path=Path(sys.argv[1])
with path.open("x", encoding="utf-8") as out:
    out.write("POSTGRES_USER=cca_shadow_admin\nPOSTGRES_DB=cca_shadow\n")
    out.write("POSTGRES_PASSWORD="+secrets.token_hex(32)+"\n")
path.chmod(0o600)
PY
sudo -n podman pull "$PG_IMAGE" >/dev/null
echo "Fetching a consistent snapshot of only the 40-table Django schema from Supabase."
sudo -n podman run --rm --network host \
  --env-file /etc/cca/oracle-stage.env \
  -v "$ROOT/backup:/backup:Z" "$PG_IMAGE" \
  sh -ec 'pg_dump --dbname="$DATABASE_URL" --schema=django_app --format=custom --no-owner --no-acl --compress=6 --file=/backup/source.dump'
sudo -n test -s "$ROOT/backup/source.dump"
sudo -n chmod 600 "$ROOT/backup/source.dump"
sudo -n podman run -d \
  --name "$DB_CONTAINER" --restart=always \
  --publish 127.0.0.1:15432:5432 \
  --env-file "$PG_ENV" \
  -v "$ROOT/data:/var/lib/postgresql/data:Z" \
  --memory 1050m --cpus 0.35 --pids-limit 70 \
  "$PG_IMAGE" \
  -c max_connections=40 -c shared_buffers=96MB \
  -c synchronous_commit=on -c fsync=on \
  >/dev/null
for i in $(seq 1 24); do
  if sudo -n podman exec "$DB_CONTAINER" pg_isready -U cca_shadow_admin -d "$DB_NAME" >/dev/null 2>&1; then
    break
  fi
  [[ "$i" -ne 24 ]] || { echo "::error::Shadow PostgreSQL did not become ready"; exit 1; }
  sleep 2
done
sudo -n podman exec "$DB_CONTAINER" psql -X -v ON_ERROR_STOP=1 \
  -U cca_shadow_admin -d "$DB_NAME" -c \
  'CREATE SCHEMA IF NOT EXISTS extensions;
   CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
   CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
   CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;' >/dev/null
echo "Restoring complete django_app schema and indexes into isolated shadow DB."
sudo -n podman exec -i "$DB_CONTAINER" \
  pg_restore --no-owner --no-acl -U cca_shadow_admin -d "$DB_NAME" \
  < <(sudo -n cat "$ROOT/backup/source.dump")
# No live app config changed. Dedicated root-only file for isolated Django tests.
sudo -n python3 - "$PG_ENV" /etc/cca/oracle-stage.env "$DJANGO_ENV" <<'PY'
from pathlib import Path
import sys
from urllib.parse import quote
pw, old, dest = map(Path, sys.argv[1:])
values={}
for line in old.read_text().splitlines():
    if "=" not in line: continue
    key,value=line.split("=",1)
    values[key]=value
password=next(line.split("=",1)[1] for line in pw.read_text().splitlines() if line.startswith("POSTGRES_PASSWORD="))
values["DATABASE_URL"]="postgresql://cca_shadow_admin:"+quote(password,safe="")+"@127.0.0.1:15432/cca_shadow"
values["DJANGO_DB_SSLMODE"]="disable"
values["DJANGO_DB_CONNECT_TIMEOUT"]="3"
values["GIT_COMMIT_SHA"]=values.get("GIT_COMMIT_SHA","shadow")
with dest.open("x") as f:
    for key,value in values.items():
        if "\n" in value or "\r" in value or "\0" in value:
            raise ValueError("Invalid env variable")
        f.write(f"{key}={value}\n")
dest.chmod(0o600)
PY
app_image="$(sudo -n podman inspect --format '{{.ImageName}}' "$APP_CONTAINER")"
[[ "$app_image" == localhost/cca-oracle:* ]] || { echo "::error::Unexpected Django app image"; exit 1; }
echo "Checking the copied schema is migration-complete (no writes)."
sudo -n podman run --rm --network host --env-file "$DJANGO_ENV" \
  "$app_image" python manage.py migrate --check --noinput
echo "Testing copied homepage, login, pedigree and typed search without changing the live site."
sudo -n podman run --rm -i --network host --env-file "$DJANGO_ENV" \
  "$app_image" python - <<'PY'
import os,statistics,time
import django
django.setup()
from django.db import connection
from django.test import Client
from django.core.cache import cache
with connection.cursor() as c:
    samples=[]
    for i in range(12):
        t=time.monotonic()
        c.execute("SELECT 1")
        assert c.fetchone()==(1,)
        samples.append((time.monotonic()-t)*1000)
print("oracle_local_postgres_sql_median_ms=%.2f" % statistics.median(samples),flush=True)
print("oracle_local_postgres_sql_max_ms=%.2f" % max(samples),flush=True)
client=Client(HTTP_HOST="canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
  HTTP_X_FORWARDED_PROTO="https", HTTP_X_CCA_EDGE="1",
  HTTP_X_CCA_ORIGIN_SECRET=os.environ["DJANGO_SECRET_KEY"])
for path in ["/","/accounts/login/","/pedigrees/virtual-mating/","/dogs/?q=Branco"]:
    cache.clear()
    start=time.monotonic()
    result=client.get(path)
    elapsed=(time.monotonic()-start)*1000
    print("shadow_django_path="+path+" http="+str(result.status_code)+" elapsed_ms=%.1f"%elapsed,flush=True)
    assert result.status_code==200, (path,result.status_code)
with connection.cursor() as c:
    c.execute("SELECT COUNT(*) FROM django_app.django_migrations")
    print("shadow_django_migrations="+str(c.fetchone()[0]))
print("SUCCESS: local shadow PostgreSQL is fully isolated; live site still uses Supabase.")
PY
sudo -n podman inspect "$DB_CONTAINER" --format 'postgres_loopback_port={{(index .NetworkSettings.Ports "5432/tcp")}}' >/dev/null
echo "PASS: Snapshot restored locally, Django smoke passed, no production DB switch."
