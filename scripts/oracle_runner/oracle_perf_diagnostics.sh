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
echo "=== Oracle Django container ==="
sudo -n podman inspect cca-oracle-staging --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} command={{.Config.Cmd}}'
sudo -n podman stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' cca-oracle-staging
echo "=== Local Django request timings (2 samples/path) ==="
for path in "/" "/accounts/login/" "/pedigrees/virtual-mating/" "/dogs/?q=Branco" "/dogs/suggestions/?q=gar&sex=male"; do
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
echo "=== Supabase SQL roundtrip from Oracle container (SELECT 1 only) ==="
sudo -n podman exec -i cca-oracle-staging python - <<'PY'
import os, time, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scripts.oracle_runner.oracle_settings')
django.setup()
from django.db import connection
with connection.cursor() as cursor:
    for i in range(5):
        t=time.monotonic()
        cursor.execute('SELECT 1')
        assert cursor.fetchone()[0] == 1
        print(f'sql_sample={i+1} elapsed_ms={(time.monotonic()-t)*1000:.1f}')
PY
echo "=== External Cloudflare live-edge request timings from Oracle host ==="
for path in "/" "/accounts/login/" "/pedigrees/virtual-mating/"; do
  curl --connect-timeout 5 --max-time 20 -sS -o /dev/null -w \
    "edge_path=$path http=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}\n" \
    "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev$path" || true
done
