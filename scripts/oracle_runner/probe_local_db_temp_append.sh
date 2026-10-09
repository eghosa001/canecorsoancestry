#!/usr/bin/env bash
# Live Oracle one-time probe of protected /tmp fd append without production changes.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(id -un)" == "opc" && "$(uname -m)" == "aarch64" ]] || exit 2
sudo -n true
if sudo -n test -e /etc/cca/oracle-db-mode; then
  echo "Already local primary; protected append probe is unnecessary."
  exit 0
fi
sudo -n test -s /etc/cca/pg-live-app.env || {
  echo "::error::No safely interrupted local application credentials to test."
  exit 1
}
target="$(mktemp)"
trap 'rm -f "$target"' EXIT
[[ "$(stat -c %a "$target")" == 600 ]]
# The owner opc opens the file in the shell's redirection, before root Python
# reads the root-only credential and prints the single expected line into FD1.
sudo -n python3 - /etc/cca/pg-live-app.env >> "$target" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1])
urls=[line.split("=",1)[1] for line in src.read_text().splitlines() if line.startswith("DATABASE_URL=")]
assert len(urls)==1 and urls[0].startswith("postgresql://cca_app:")
assert urls[0].endswith("@cca-pg-shadow:5432/cca_live")
assert not any(x in urls[0] for x in ("\r","\n","\0"))
print("DATABASE_URL="+urls[0])
PY
python3 - "$target" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1])
lines=path.read_text().splitlines()
assert len(lines)==1
assert lines[0].startswith("DATABASE_URL=postgresql://cca_app:")
assert lines[0].endswith("@cca-pg-shadow:5432/cca_live")
PY
echo "PASS: Oracle protected /tmp append using root-only secret works; credentials never logged."
