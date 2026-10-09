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
echo "inside_container_flag:"
sudo -n podman exec cca-oracle-staging python -c \
 'from pathlib import Path; p=Path("/run/cca/maintenance.flag"); print("mounted="+str(p.parent.exists()),"flag="+str(p.exists()))' || true
echo "maintenance_request="$(curl --max-time 10 -sS -o /dev/null -w '%{http_code}' \
 -H "X-CCA-Edge: 1" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
 -H "X-Forwarded-Proto: https" http://127.0.0.1:18080/accounts/login/)
echo "recent_error_categories:"
sudo -n journalctl -u cca-oracle-staging.service --since "45 seconds ago" \
  --no-pager -o cat | grep -E "Traceback|Error:|Exception:|Permission denied|failed|500" | tail -25 || true
sudo -n rm -f "$flag"
trap - EXIT
echo "after="$(curl --max-time 12 -sS -o /dev/null -w '%{http_code}' \
 -H "X-CCA-Edge: 1" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
 -H "X-Forwarded-Proto: https" http://127.0.0.1:18080/accounts/login/)
