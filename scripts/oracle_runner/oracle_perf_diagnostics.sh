#!/usr/bin/env bash
# One-time, read-only Oracle performance diagnosis; guarded main/repo runner.
set -euo pipefail
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(uname -m)" == "aarch64" &&
   "$(id -un)" == "opc" ]] || exit 2
set +x
echo "=== Oracle VM capacity (no secrets) ==="
printf 'host_cpus='; nproc
grep -m1 -E 'MemTotal:' /proc/meminfo
printf 'host_load='; cat /proc/loadavg | cut -d' ' -f1-3
printf 'available_disk='; df -h / | tail -1 | awk '{print $4}'
echo "=== Active Django release after CPU tune ==="
curl --connect-timeout 3 --max-time 8 -fsS http://127.0.0.1:18080/healthz/ | python3 -c 'import json,sys; p=json.load(sys.stdin); print("release="+str(p.get("release", "unknown"))+" status="+str(p.get("status", "unknown")))'
echo "=== Post-cutover service and database identity ==="
sudo -n systemctl is-active --quiet cca-oracle-staging.service
sudo -n systemctl is-active --quiet cca-pg-shadow.service
sudo -n podman container exists cca-pg-shadow
mode="$(sudo -n cat /etc/cca/oracle-db-mode)"
[[ "$mode" == local ]] || { echo "::error::Oracle-local DB mode is not active"; exit 1; }
health="$(curl --connect-timeout 3 --max-time 10 -fsS http://127.0.0.1:18080/healthz/)"
printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("live_db_backend="+str(d.get("database_backend"))+" status="+str(d.get("status"))); assert d.get("database_backend")=="oracle-local" and d.get("status")=="ok"'
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1 -U cca_shadow_admin -d cca_live
echo "=== Oracle Django container ==="
sudo -n podman inspect cca-oracle-staging --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} command={{.Config.Cmd}}'
sudo -n podman stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' cca-oracle-staging
echo "=== Local Django request timings (2 samples/path) ==="
for path in "/" "/accounts/login/" "/pedigrees/virtual-mating/" "/dogs/?q=" "/dogs/?q=Branco" "/dogs/suggestions/?q=gar&sex=male"; do
  for n in 1 2; do
    headers_file="$(mktemp)"
    timing="$(curl -sS --connect-timeout 3 --max-time 20 -o /dev/null -D "$headers_file" -w 'http=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}' \
      -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
      -H 'X-CCA-Edge: 1' \
      -H 'X-Forwarded-Proto: https' \
      -H 'X-Forwarded-Host: canecorsoancestry-site-edge.aighewieghosa111.workers.dev' \
      "http://127.0.0.1:18080$path" || true)"
    app="$(tr -d '\r' < "$headers_file" | grep -i '^server-timing:' | head -1 | sed -E 's/^server-timing:[[:space:]]*//' || true)"
    rm -f "$headers_file"
    printf 'path=%s sample=%d %s app=%s\n' "$path" "$n" "$timing" "$app"
  done
done
echo "=== Active Oracle-local PostgreSQL SQL roundtrip (SELECT 1 only) ==="
sudo -n podman exec -i cca-oracle-staging python - <<'PY'
import os, time, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scripts.oracle_runner.oracle_settings')
django.setup()
from django.db import connection
from statistics import median
elapsed=[]
with connection.cursor() as cursor:
    for i in range(5):
        t=time.monotonic()
        cursor.execute('SELECT 1')
        assert cursor.fetchone()[0] == 1
        ms=(time.monotonic()-t)*1000
        elapsed.append(ms)
        print(f'sql_sample={i+1} elapsed_ms={ms:.3f}')
print(f'active_database_sql_median_ms={median(elapsed):.3f}',flush=True)
assert median(elapsed)<20, "Local SQL median exceeded 20ms; investigate VM contention."
PY
echo "=== Public routes and database post-cutover smoke ==="
for path in "/" "/accounts/login/" "/pedigrees/virtual-mating/" "/dogs/?q=" "/dogs/?q=Branco"; do
  code="$(curl -sS --connect-timeout 5 --max-time 20 -o /dev/null -w '%{http_code}' \
    "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev$path" || true)"
  echo "public_smoke=$path http=$code"
  [[ "$code" == 200 ]] || { echo "::error::Public route $path failed after database cutover"; exit 1; }
done
echo "=== External Cloudflare live-edge request timings from Oracle host ==="
for path in "/" "/accounts/login/" "/pedigrees/virtual-mating/"; do
  curl --connect-timeout 5 --max-time 20 -sS -o /dev/null -w \
    "edge_path=$path http=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}\n" \
    "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev$path" || true
done
