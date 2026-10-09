#!/usr/bin/env bash
# One-time guarded Oracle capacity tune and deployment of merged query improvement.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" ]] || exit 2
[[ "$GITHUB_REF" == "refs/heads/main" ]] || exit 2
[[ "$(uname -m)" == "aarch64" && "$(id -un)" == "opc" ]] || exit 2
sudo -n true
command -v podman >/dev/null
[[ -n "$DJANGO_SECRET_KEY" && -n "$SUPABASE_DATABASE_URL" ]] || exit 2
readonly NAME=cca-oracle-staging
readonly UNIT=cca-oracle-staging.service
readonly ORIGIN=http://127.0.0.1:18080
readonly PUBLIC=https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev
readonly OLD_CPUS=0.75
readonly NEW_CPUS=0.90

mem_total="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
mem_free="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
disk_free="$(df -Pk / | awk 'END {print $4}')"
echo "Oracle capacity: cpu_cores=$(nproc) memory_total_mb=$((mem_total/1024)) memory_available_mb=$((mem_free/1024)) disk_free_gb=$((disk_free/1048576))"
[[ "$(nproc)" -ge 1 && "$mem_total" -ge 4000000 &&
   "$mem_free" -ge 700000 && "$disk_free" -ge 6291456 ]] || {
  echo "::error::Oracle does not have enough spare capacity for a safe update."; exit 1;
}
sudo -n systemctl is-active --quiet "$UNIT"
old_image="$(sudo -n podman inspect --format '{{.ImageName}}' "$NAME")"
old_cpu="$(sudo -n podman inspect --format '{{.HostConfig.NanoCpus}}' "$NAME")"
[[ "$old_image" == localhost/cca-oracle:* && ( "$old_cpu" == 750000000 || "$old_cpu" == 900000000 ) ]] || {
  echo "::error::Unexpected container; refusing production changes."; exit 1;
}
curl --connect-timeout 3 --max-time 12 -fsS "$ORIGIN/healthz/" >/dev/null

old_env="/etc/cca/oracle-stage.env.preperf-$GITHUB_RUN_ID"
sudo -n cp -p /etc/cca/oracle-stage.env "$old_env"
succeeded=no
restore_if_needed() {
  code=$?
  trap - EXIT
  if [[ "$succeeded" != yes ]]; then
    echo "::warning::Update failed; attempting to restore the old Django release."
    sudo -n cp -p "$old_env" /etc/cca/oracle-stage.env || true
    if ! sudo -n systemctl is-active --quiet "$UNIT" ||
       ! curl --connect-timeout 2 --max-time 6 -fsS "$ORIGIN/healthz/" >/dev/null 2>&1; then
      sudo -n systemctl stop "$UNIT" >/dev/null 2>&1 || true
      sudo -n podman rm -f "$NAME" >/dev/null 2>&1 || true
      if sudo -n podman create --name "$NAME" \
          --publish 127.0.0.1:18080:8080 \
          --env-file /etc/cca/oracle-stage.env \
          --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
          --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
          --pids-limit 128 --memory 1800m --cpus "$OLD_CPUS" \
          "$old_image" \
          gunicorn config.wsgi:application --bind 0.0.0.0:8080 \
          --workers 1 --threads 4 --timeout 60 --worker-tmp-dir /tmp \
          --access-logfile - --error-logfile - >/dev/null; then
        sudo -n systemctl start "$UNIT" || true
      fi
    else
      sudo -n podman update --cpus "$OLD_CPUS" "$NAME" >/dev/null || true
    fi
    sudo -n systemctl start cca-cloudflared-vpc.service >/dev/null 2>&1 || true
  fi
  sudo -n rm -f "$old_env"
  exit "$code"
}
trap restore_if_needed EXIT

sudo -n podman update --cpus "$NEW_CPUS" "$NAME" >/dev/null
[[ "$(sudo -n podman inspect --format '{{.HostConfig.NanoCpus}}' "$NAME")" == 900000000 ]]
curl --connect-timeout 3 --max-time 12 -fsS "$ORIGIN/healthz/" >/dev/null
echo "In-place CPU quota: 0.75 -> 0.90 of the VM's existing core."

# Build/install the already-tested Django release, including fast public cards.
# Existing staging script checks schema and builds before replacing live Django.
bash scripts/oracle_runner/stage_django.sh
sudo -n systemctl start cca-cloudflared-vpc.service >/dev/null 2>&1 || true
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service
[[ "$(sudo -n podman inspect --format '{{.HostConfig.NanoCpus}}' "$NAME")" == 900000000 ]]

for i in $(seq 1 10); do
  code="$(curl -sS --connect-timeout 5 --max-time 15 -o /dev/null -w '%{http_code}' "$PUBLIC/accounts/login/" || true)"
  if [[ "$code" == 200 ]]; then break; fi
  [[ "$i" -ne 10 ]] || { echo "::error::Public login failed, HTTP $code"; exit 1; }
  sleep 3
done
succeeded=yes
echo "SUCCESS: current main code and 0.90 CPU quota live on Oracle; Supabase remains the database."
{
  echo "## Oracle performance rollout"
  echo "- Django release: $GITHUB_SHA"
  echo "- Django CPU limit: 0.75 → 0.90 of the existing core"
  echo "- Public login: HTTP 200"
  echo "- Supabase, Cloudflare tunnel, R2 and Paystack: unchanged"
} >> "$GITHUB_STEP_SUMMARY"
