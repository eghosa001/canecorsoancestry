#!/usr/bin/env bash
# Manual-only Oracle Django update; never changes Cloudflare routing or opens public ports.
# IMPORTANT: If Oracle is production, this briefly restarts the live Django origin.
set -euo pipefail
umask 077

readonly REPO="eghosa001/canecorsoancestry"
readonly PUBLIC_SITE="https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
readonly MEDIA_EDGE="https://canecorsoancestry-edge.aighewieghosa111.workers.dev"

if [[ "$GITHUB_REPOSITORY" != "$REPO" ||
      "$GITHUB_REF" != "refs/heads/main" ||
      "$(uname -m)" != "aarch64" ||
      "$(id -un)" != "opc" ]]; then
  echo "::error::Oracle staging may run only as opc, on CCA/main, ARM64." >&2
  exit 1
fi
for name in DJANGO_SECRET_KEY; do
  if [[ -z "$(printenv "$name" || true)" ]]; then
    echo "::error::Missing required GitHub Actions secret: $name" >&2
    exit 1
  fi
done
command -v sudo >/dev/null
sudo -n true
DB_MODE="$(sudo -n cat /etc/cca/oracle-db-mode)"
[[ "$DB_MODE" == local ]] || { echo "::error::Only verified Oracle-local PostgreSQL is permitted in production."; exit 1; }
export CCA_ORACLE_DB_MODE="$DB_MODE"
if ! command -v podman >/dev/null; then
  echo "Installing Oracle Linux Podman container engine."
  sudo -n dnf -y install podman >/dev/null
fi
readonly PODMAN_BIN="$(command -v podman)"
command -v curl >/dev/null
command -v python3 >/dev/null
if [[ "$(df -Pk / | awk 'END {print $4}')" -lt 6291456 ]]; then
  echo "::error::Less than 6 GiB available; refusing to risk runner disk exhaustion." >&2
  exit 1
fi

# The event SHA differs from the triggering commit for workflow_run events.
# Always build and publish the commit actually checked out on protected main.
export CCA_RELEASE_SHA="$(git rev-parse HEAD)"
[[ "$CCA_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
readonly IMAGE="localhost/cca-oracle:$(printf '%s' "$CCA_RELEASE_SHA" | cut -c1-12)"
readonly APP_SERVICE="cca-oracle-staging.service"
readonly APP_CONTAINER="cca-oracle-staging"
readonly APP_ENV="/etc/cca/oracle-stage.env"
temporary_env="$(mktemp)"
temporary_unit="$(mktemp)"
probe_output="$(mktemp)"
trap 'rm -f "$temporary_env" "$temporary_unit" "$probe_output"' EXIT

# Credentials remain in the GitHub secret store and a root-owned 0600 runtime
# file; never log, echo or upload environment content as an Actions artifact.
python3 - "$temporary_env" <<'PY'
import base64
import os
import sys
from pathlib import Path

secret = os.environ["DJANGO_SECRET_KEY"]
email_keys = ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
email_ready = all(os.environ.get(key, "") for key in email_keys)
values = {
    "DJANGO_SETTINGS_MODULE": "scripts.oracle_runner.oracle_settings",
    "DJANGO_SECRET_KEY": secret,
    "DJANGO_ALLOWED_HOSTS": (
        "canecorsoancestry-site-edge.aighewieghosa111.workers.dev,"
        "127.0.0.1,localhost"
    ),
    "DJANGO_CSRF_TRUSTED_ORIGINS": (
        "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
    ),
    "SITE_URL": "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
    "DJANGO_DB_SCHEMA": "django_app",
    "DJANGO_DB_SSLMODE": "disable",
    "DJANGO_DB_EXTRA_SCHEMAS": "extensions,public",
    "DJANGO_DB_CONN_MAX_AGE": "300",
    "DJANGO_DB_CONNECT_TIMEOUT": "3",
    "DJANGO_TIME_ZONE": "Africa/Lagos",
    "DJANGO_HSTS_SECONDS": "31536000",
    "DJANGO_HSTS_INCLUDE_SUBDOMAINS": "1",
    "DJANGO_HSTS_PRELOAD": "1",
    "R2_GATEWAY_URL": "https://canecorsoancestry-edge.aighewieghosa111.workers.dev",
    "MEDIA_EDGE_BASE_URL": "https://canecorsoancestry-edge.aighewieghosa111.workers.dev",
    "MEDIA_EDGE_URL_TTL": "300",
    "R2_GATEWAY_SIGNING_KEY": base64.b64encode(secret.encode()).decode(),
    "PAYSTACK_SECRET_KEY": os.environ.get("PAYSTACK_SECRET_KEY", ""),
    "EMAIL_HOST": os.environ.get("EMAIL_HOST", ""),
    "EMAIL_HOST_USER": os.environ.get("EMAIL_HOST_USER", ""),
    "EMAIL_HOST_PASSWORD": os.environ.get("EMAIL_HOST_PASSWORD", ""),
    "DEFAULT_FROM_EMAIL": (
        os.environ.get("DEFAULT_FROM_EMAIL")
        or os.environ.get("EMAIL_HOST_USER", "")
        or "webmaster@localhost"
    ),
    "ACCOUNT_EMAIL_ENABLED": "1" if email_ready else "0",
    "REQUIRE_EMAIL_VERIFICATION": "1" if email_ready else "0",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_PORT": "587",
    "EMAIL_USE_TLS": "1",
    "EMAIL_TIMEOUT": "10",
    "ANCESTRY_EMAIL_NOTIFICATIONS": "0",
    "GUNICORN_WORKERS": "1",
    "GUNICORN_THREADS": "4",
    "GUNICORN_TIMEOUT": "60",
    "GIT_COMMIT_SHA": os.environ["CCA_RELEASE_SHA"],
}
for key, value in values.items():
    if any(char in str(value) for char in ("\r", "\n", "\0")):
        raise SystemExit(f"Unsafe newline or NUL in {key}")
Path(sys.argv[1]).write_text(
    "".join(f"{key}={value}\n" for key, value in values.items()),
    encoding="utf-8",
)
PY
chmod 600 "$temporary_env"

echo "Building pinned CCA commit for linux/arm64 on Oracle."
sudo -n "$PODMAN_BIN" build --pull=missing --tag "$IMAGE" .

run_network=(--network cca-private)
sudo -n test -s /etc/cca/pg-live-app.env || {
  echo "::error::Local DB mode requires a verified private Postgres connection"; exit 1;
  }
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1     -U cca_shadow_admin -d cca_live >/dev/null || {
  echo "::error::Local primary database is unavailable"; exit 1;
  }
# On hardened Oracle Linux, root cannot open an opc-owned mktemp(0600)
# file in /tmp for writing (fs.protected_regular). Have the unprivileged
# shell open the destination, while root *only* reads the 0600 live DB
# credential and writes its validated value to that existing descriptor.
# The URL never enters argv, job logs, or shell tracing.
sudo -n python3 - /etc/cca/pg-live-app.env >> "$temporary_env" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1])
urls=[line.split("=",1)[1] for line in src.read_text().splitlines() if line.startswith("DATABASE_URL=")]
assert len(urls)==1
assert urls[0].endswith("@cca-pg-shadow:5432/cca_live")
assert urls[0].startswith("postgresql://cca_app:")
assert not any(char in urls[0] for char in ("\n","\r","\0"))
print("DATABASE_URL="+urls[0])
PY
echo "Using verified Oracle-local PostgreSQL primary via private network."

echo "Checking the production schema has no outstanding migrations."
sudo -n "$PODMAN_BIN" run --rm "${run_network[@]}" --env-file "$temporary_env" \
  "$IMAGE" python manage.py migrate --check --noinput

sudo -n install -d -m 700 /etc/cca
sudo -n install -d -m 755 /var/lib/cca/control
sudo -n install -o root -g root -m 600 "$temporary_env" "$APP_ENV"

# Bind only on host loopback; Oracle ingress and Cloudflare routing remain
# UNCHANGED. Override Dockerfile CMD because it runs write-mode migrations.
if sudo -n systemctl is-active --quiet "$APP_SERVICE"; then
  sudo -n systemctl stop "$APP_SERVICE"
fi
sudo -n "$PODMAN_BIN" rm -f "$APP_CONTAINER" >/dev/null 2>&1 || true
sudo -n "$PODMAN_BIN" create \
  "${run_network[@]}" \
  --name "$APP_CONTAINER" \
  --publish 127.0.0.1:18080:8080 \
  --env-file "$APP_ENV" \
  --volume /var/lib/cca/control:/run/cca:ro,Z \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  --user 65532:65532 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 128 \
  --memory 1800m \
  --cpus 0.90 \
  "$IMAGE" \
  gunicorn config.wsgi:application --bind 0.0.0.0:8080 \
  --workers 1 --threads 4 --timeout 60 --worker-tmp-dir /tmp \
  --access-logfile - --error-logfile - >/dev/null

sudo -n systemctl is-active --quiet cca-pg-shadow.service || {
  echo "::error::Local DB requires systemd-managed PostgreSQL"; exit 1;
}
db_after="cca-pg-shadow.service"
db_requires="Requires=cca-pg-shadow.service"
cat > "$temporary_unit" <<UNIT
[Unit]
Description=Cane Corso Ancestry Django Oracle staging (loopback only)
After=network-online.target $db_after
Wants=network-online.target
$db_requires

[Service]
Type=simple
ExecStart=$PODMAN_BIN start --attach $APP_CONTAINER
ExecStop=$PODMAN_BIN stop --time 20 $APP_CONTAINER
Restart=always
RestartSec=5
TimeoutStartSec=90
TimeoutStopSec=45

[Install]
WantedBy=multi-user.target
UNIT
sudo -n install -o root -g root -m 644 "$temporary_unit" "/etc/systemd/system/$APP_SERVICE"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now "$APP_SERVICE"
sudo -n systemctl is-active --quiet "$APP_SERVICE"

# The Oracle application restart can stop the dependent Cloudflare VPC tunnel
# cleanly. systemd Restart=always does not revive a service explicitly stopped
# by a dependent unit. Bring the private ingress back on EVERY Django release.
readonly VPC_SERVICE="cca-cloudflared-vpc.service"
sudo -n systemctl cat "$VPC_SERVICE" >/dev/null 2>&1 || {
  echo "::error::Production Cloudflare VPC tunnel systemd unit is missing."; exit 1;
}
sudo -n systemctl enable --now "$VPC_SERVICE"
sudo -n systemctl is-active --quiet "$VPC_SERVICE" || {
  echo "::error::Private Cloudflare VPC connector did not restart after Django."; exit 1;
}
echo "PASS: Oracle private Cloudflare VPC connector is active and boot-enabled."

readonly URL="http://127.0.0.1:18080"
echo "Checking release, direct-origin access, sign-in, and R2 upload/read/delete."
ready=0
for attempt in $(seq 1 25); do
  status="$(curl --connect-timeout 2 --max-time 8 -sS -o "$probe_output" -w '%{http_code}' \
      "$URL/healthz/" || true)"
  if [[ "$status" == 200 ]] && \
     python3 - "$probe_output" "$CCA_RELEASE_SHA" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ok"
assert payload.get("release") == sys.argv[2]
PY
  then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo "::error::Oracle Django release/DB readiness failed."; exit 1; }

code="$(curl --connect-timeout 2 --max-time 10 -sS -o /dev/null -w '%{http_code}' "$URL/accounts/login/")"
[[ "$code" == 403 ]] || { echo "::error::Direct-origin protection failed: HTTP $code"; exit 1; }
code="$(curl --connect-timeout 2 --max-time 20 -sS -o /dev/null -w '%{http_code}' \
  -H 'X-CCA-Edge: 1' \
  -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
  -H "X-CCA-Maintenance-Probe: $DJANGO_SECRET_KEY" \
  -H 'X-Forwarded-Proto: https' \
  "$URL/accounts/login/")"
[[ "$code" == 200 ]] || { echo "::error::Staged Django sign-in failed: HTTP $code"; exit 1; }
code="$(curl --connect-timeout 2 --max-time 40 -sS -o "$probe_output" -w '%{http_code}' \
  -X POST -H 'X-CCA-Edge: 1' \
  -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
  -H "X-CCA-Storage-Probe: $DJANGO_SECRET_KEY" \
  -H "X-CCA-Maintenance-Probe: $DJANGO_SECRET_KEY" \
  -H 'X-Forwarded-Proto: https' \
  "$URL/__internal/storage-probe/")"
if [[ "$code" != 200 ]] || ! python3 - "$probe_output" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ok" and payload.get("storage") == "r2"
PY
then
  echo "::error::Oracle -> R2 storage probe failed (HTTP $code)." >&2
  exit 1
fi

# A local Django 200 is not proof that the public Worker can reach Oracle.
# Fail the release if the user-facing route is not reachable or still serves
# the previous commit. Public /healthz/ is uncached and discloses no secrets.
readonly PUBLIC_EDGE="https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
public_ready=0
for attempt in $(seq 1 20); do
  public_status="$(curl --connect-timeout 4 --max-time 12 -sS -o "$probe_output" -w '%{http_code}' "$PUBLIC_EDGE/healthz/" || true)"
  if [[ "$public_status" == 200 ]] && python3 - "$probe_output" "$CCA_RELEASE_SHA" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ok"
assert payload.get("release") == sys.argv[2]
assert payload.get("database_backend") == "oracle-local"
PY
  then
    home_status="$(curl --connect-timeout 4 --max-time 15 -sS -o /dev/null -w '%{http_code}' "$PUBLIC_EDGE/" || true)"
    if [[ "$home_status" == 200 ]]; then
      public_ready=1
      break
    fi
  fi
  sleep 3
done
[[ "$public_ready" == 1 ]] || {
  echo "::error::Cloudflare public homepage or release identity is not healthy after Oracle deployment."; exit 1;
}
echo "PASS: Cloudflare public homepage HTTP 200 and exact Django release SHA verified."

echo "PASS: Oracle CCA stage is healthy at 127.0.0.1:18080; DB and R2 work."
echo "Oracle container updated; Cloudflare routing was not modified. If Oracle is serving production, this was a live Django restart."
{
  echo "## Oracle Django container update completed (Cloudflare routing unchanged)"
  echo ""
  echo "- ARM64 source commit: $CCA_RELEASE_SHA"
  echo "- Service: $APP_SERVICE (enabled)"
  echo "- Local origin: http://127.0.0.1:18080 (loopback only)"
  echo "- Database backend: $DB_MODE; schema migrations current"
  echo "- Cloudflare R2: authenticated upload/read/delete probe passed"
  echo "- Edge authentication: direct access denied; trusted login succeeded"
  echo "- Cloudflare private VPC tunnel: active and enabled after app restart"
  echo "- Cloudflare public homepage: HTTP 200; exact Django SHA verified"
  echo "- Public Cloudflare Worker origin: unchanged (Oracle)"
} >> "$GITHUB_STEP_SUMMARY"
