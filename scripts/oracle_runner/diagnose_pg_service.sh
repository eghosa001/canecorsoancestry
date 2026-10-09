#!/usr/bin/env bash
# Read-only inspect Podman state after guarded DB promotion stopped at exit 3.
set -euo pipefail
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(id -un)" == "opc" && "$(uname -m)" == aarch64 ]] || exit 2
sudo -n true
echo "=== Persistent Postgres service ==="
sudo -n systemctl is-enabled cca-pg-shadow.service || true
sudo -n systemctl is-active cca-pg-shadow.service || true
sudo -n systemctl show cca-pg-shadow.service \
  --property=ActiveState,SubState,Result,NRestarts,MainPID,ExecMainStatus --no-pager || true
echo "=== Podman DB container identity ==="
sudo -n podman ps -a --format 'name={{.Names}} status={{.Status}} id={{.ID}}' | grep -E 'cca-(pg-shadow|oracle-staging)' || true
if sudo -n podman container exists cca-pg-shadow; then
  sudo -n podman inspect cca-pg-shadow --format 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} restart={{.HostConfig.RestartPolicy.Name}} image={{.ImageName}}'
  sudo -n podman stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' cca-pg-shadow || true
else
  echo "postgres_container_missing=true"
fi
echo "=== Last postgres service events (redact access data) ==="
sudo -n journalctl -u cca-pg-shadow.service --since '20 min ago' --no-pager -o cat \
  | grep -E 'Main process exited|Failed with result|Started|Stopped|stop job|No such container|executable file|permission denied|killed|oom|Failed to|cannot|error|Error|code=|status=' \
  | tail -35 || true
echo "=== Live Django source marker ==="
curl -fsS --connect-timeout 3 --max-time 10 http://127.0.0.1:18080/healthz/ \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("django="+d.get("status","?")+" database_backend="+d.get("database_backend","?"))'
echo "=== Exact guarded cutover prerequisite exit codes ==="
set +e
sudo -n podman container exists cca-pg-shadow >/dev/null 2>&1; echo "pg_exists_rc=$?"
sudo -n systemctl is-active --quiet cca-oracle-staging.service; echo "django_unit_rc=$?"
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service; echo "vpc_tunnel_unit_rc=$?"
sudo -n podman inspect cca-oracle-staging --format '{{json .Mounts}}' | grep -q '"/run/cca"'; echo "control_mount_rc=$?"
sudo -n test "$(df -Pk / | awk 'END{print $4}')" -gt 6291456; echo "disk_guard_rc=$?"
sudo -n test "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -gt 1000000; echo "ram_guard_rc=$?"
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1 -U cca_shadow_admin -d cca_shadow >/dev/null; echo "postgres_ready_rc=$?"
set -e
echo "=== Safe cutover markers (existence only) ==="
for f in /etc/cca/oracle-db-mode /etc/cca/pg-live-app.env /var/lib/cca/control/maintenance.flag; do
 if sudo -n test -e "$f"; then echo "$f EXISTS"; else echo "$f absent"; fi
done
echo "PASS: no diagnostic changes were made."
