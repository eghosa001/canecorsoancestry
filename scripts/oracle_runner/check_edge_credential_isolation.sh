#!/usr/bin/env bash
# Live, read-only edge isolation regression. Never echo credential values.
set -euo pipefail
umask 077
[[ "${GITHUB_REPOSITORY:-}" == "eghosa001/canecorsoancestry" &&
    "${GITHUB_REF:-}" == "refs/heads/main" &&
    "$(uname -m)" == "aarch64" &&
    "$(id -un)" == "opc" ]] || exit 2
test "$(sudo -n cat /etc/cca/oracle-db-mode)" = local
sudo -n systemctl is-active --quiet cca-oracle-staging.service
test -n "${DJANGO_SECRET_KEY:-}"
derived="$(python3 - <<'PY'
import hashlib
import hmac
import os
print(hmac.new(
    os.environ["DJANGO_SECRET_KEY"].encode("utf-8"),
    b"cca-origin-edge-auth-v1", hashlib.sha256,
).hexdigest())
PY
)"
[[ "$derived" != "$DJANGO_SECRET_KEY" ]]
endpoint="http://127.0.0.1:18080/accounts/login/"
common=(--silent --show-error --connect-timeout 4 --max-time 15
  -H "X-CCA-Edge: 1" -H "X-Forwarded-Proto: https"
  -o /dev/null -w '%{http_code}')
accepted="$(curl "${common[@]}" -H "X-CCA-Origin-Secret: $derived" "$endpoint")"
rejected="$(curl "${common[@]}" -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" "$endpoint")"
anonymous="$(curl "${common[@]}" "$endpoint")"
test "$accepted" = 200 || { echo "::error::Derived edge credential rejected; HTTP $accepted"; exit 1; }
test "$rejected" = 403 || { echo "::error::Root Django signing credential still authenticates origin! HTTP $rejected"; exit 1; }
test "$anonymous" = 403 || { echo "::error::Origin allowed unsigned direct request; HTTP $anonymous"; exit 1; }
echo "PASS: derived Worker credential authenticates; root Django secret and unsigned direct origin are both denied."
