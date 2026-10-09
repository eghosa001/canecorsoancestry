#!/usr/bin/env bash
# Temporarily probe migration maintenance response, always remove flag.
set -euo pipefail
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
 "$GITHUB_REF" == "refs/heads/main" &&
 "$(id -un)" == "opc" && "$(uname -m)" == aarch64 ]] || exit 2
sudo -n true
flag=/var/lib/cca/control/maintenance.flag
sudo -n test ! -e "$flag" || { echo "::error::Site already in maintenance; do not override"; exit 1; }
cleanup() { sudo -n rm -f "$flag"; }
trap cleanup EXIT
echo "before="$(curl --max-time 10 -sS -o /dev/null -w '%{http_code}' \
 -H "X-CCA-Edge: 1" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
 -H "X-Forwarded-Proto: https" http://127.0.0.1:18080/accounts/login/)
sudo -n install -o root -g root -m 644 /dev/null "$flag"
sudo -n chcon --reference="$(dirname "$flag")" "$flag"
echo "=== Host flag permissions and SELinux labels ==="
sudo -n ls -ldZ /var/lib/cca /var/lib/cca/control "$flag" || true
sudo -n namei -l "$flag" || true
echo "=== Container mount, labels and access ==="
sudo -n podman inspect cca-oracle-staging --format 'process_label={{.ProcessLabel}} mount_label={{.MountLabel}} mounts={{json .Mounts}}'
sudo -n podman exec cca-oracle-staging python - <<'PY' || true
import os
for p in ("/run", "/run/cca", "/run/cca/maintenance.flag"):
    try:
        s=os.stat(p)
        print("access_path="+p+" uid="+str(s.st_uid)+" gid="+str(s.st_gid)+" mode="+oct(s.st_mode & 0o777))
    except OSError as e:
        print("access_path="+p+" errno="+str(e.errno)+" type="+type(e).__name__)
PY
echo "inside_container_flag:"
sudo -n podman exec cca-oracle-staging python -c \
 'from pathlib import Path; p=Path("/run/cca/maintenance.flag"); print("mounted="+str(p.parent.exists()),"flag="+str(p.exists()))' || true
status="$(curl --max-time 10 -sS -o /dev/null -w '%{http_code}' \
 -H "X-CCA-Edge: 1" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
 -H "X-Forwarded-Proto: https" http://127.0.0.1:18080/accounts/login/)"
echo "maintenance_request=$status"
[[ "$status" == 503 ]] || { echo "::error::Expected 503 with correctly labelled flag, got $status"; exit 1; }
echo "recent_error_categories:"
sudo -n journalctl -u cca-oracle-staging.service --since "45 seconds ago" \
  --no-pager -o cat | grep -E "Traceback|Error:|Exception:|Permission denied|failed|500" | tail -25 || true
sudo -n rm -f "$flag"
trap - EXIT
after="$(curl --max-time 12 -sS -o /dev/null -w '%{http_code}' \
 -H "X-CCA-Edge: 1" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
 -H "X-Forwarded-Proto: https" http://127.0.0.1:18080/accounts/login/)"
echo "after=$after"
[[ "$after" == 200 ]] || { echo "::error::Expected normal login HTTP 200 after flag removal"; exit 1; }
