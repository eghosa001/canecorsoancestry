#!/usr/bin/env bash
# Manual-only, non-cutover Oracle Django staging. Never opens public ports.
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
for name in DJANGO_SECRET_KEY SUPABASE_DATABASE_URL; do
  if [[ -z "$(printenv "$name" || true)" ]]; then
    echo "::error::Missing required GitHub Actions secret: $name" >&2
    exit 1
  fi
done
command -v sudo >/dev/null
sudo -n true
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

readonly IMAGE="localhost/cca-oracle:$(printf '%s' "$GITHUB_SHA" | cut -c1-12)"
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
    "SUPABASE_DATABASE_URL": os.environ["SUPABASE_DATABASE_URL"],
    "DJANGO_SETTINGS_MODULE": "config.settings.oracle",
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
    "DJANGO_DB_SSLMODE": "require",
    "DJANGO_DB_EXTRA_SCHEMAS": "extensions,public",
    "DJANGO_DB_CONN_MAX_AGE": "300",
    "DJANGO_DB_CONNECT_TIMEOUT": "5",
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
    "GIT_COMMIT_SHA": os.environ["GITHUB_SHA"],
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

echo "Resolving the working Supabase session pooler from Oracle (no schema writes)."
pooler_url="$(sudo -n "$PODMAN_BIN" run --rm \
  --env-file "$temporary_env" "$IMAGE" \
  python scripts/discover_supabase_session_pooler.py)"
[[ "$pooler_url" == postgresql://* ]] || { echo "::error::Supabase pooler inaccessible from Oracle."; exit 1; }
echo "::add-mask::$pooler_url"
python3 - "$temporary_env" "$pooler_url" <<'PY'
from pathlib import Path
import sys

path, url = sys.argv[1:3]
if any(char in url for char in ("\r", "\n", "\0")):
    raise SystemExit("Invalid database URL")
with Path(path).open("a", encoding="utf-8") as stream:
    stream.write(f"DATABASE_URL={url}\n")
PY
# The temporary discovery credential is not required by the running server.
sed -i '/^SUPABASE_DATABASE_URL=/d' "$temporary_env"

echo "Checking the production schema has no outstanding migrations."
sudo -n "$PODMAN_BIN" run --rm --env-file "$temporary_env" \
  "$IMAGE" python manage.py migrate --check --noinput

sudo -n install -d -m 700 /etc/cca
sudo -n install -o root -g root -m 600 "$temporary_env" "$APP_ENV"

# Bind only on host loopback; Oracle ingress and Cloudflare routing remain
# UNCHANGED. Override Dockerfile CMD because it runs write-mode migrations.
if sudo -n systemctl is-active --quiet "$APP_SERVICE"; then
  sudo -n systemctl stop "$APP_SERVICE"
fi
sudo -n "$PODMAN_BIN" rm -f "$APP_CONTAINER" >/dev/null 2>&1 || true
sudo -n "$PODMAN_BIN" create \
  --name "$APP_CONTAINER" \
  --publish 127.0.0.1:18080:8080 \
  --env-file "$APP_ENV" \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  --user 65532:65532 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 128 \
  --memory 1800m \
  --cpus 0.75 \
  "$IMAGE" \
  gunicorn config.wsgi:application --bind 0.0.0.0:8080 \
  --workers 1 --threads 4 --timeout 60 --worker-tmp-dir /tmp \
  --access-logfile - --error-logfile - >/dev/null

cat > "$temporary_unit" <<UNIT
[Unit]
Description=Cane Corso Ancestry Django Oracle staging (loopback only)
After=network-online.target
Wants=network-online.target

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

readonly URL="http://127.0.0.1:18080"
echo "Checking release, direct-origin access, sign-in, and R2 upload/read/delete."
ready=0
for attempt in $(seq 1 25); do
  status="$(curl --connect-timeout 2 --max-time 8 -sS -o "$probe_output" -w '%{http_code}' \
      "$URL/healthz/" || true)"
  if [[ "$status" == 200 ]] && \
     python3 - "$probe_output" "$GITHUB_SHA" <<'PY'
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
  -H 'X-Forwarded-Proto: https' \
  "$URL/accounts/login/")"
[[ "$code" == 200 ]] || { echo "::error::Staged Django sign-in failed: HTTP $code"; exit 1; }
code="$(curl --connect-timeout 2 --max-time 40 -sS -o "$probe_output" -w '%{http_code}' \
  -X POST -H 'X-CCA-Edge: 1' \
  -H "X-CCA-Origin-Secret: $DJANGO_SECRET_KEY" \
  -H "X-CCA-Storage-Probe: $DJANGO_SECRET_KEY" \
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

echo "PASS: Oracle CCA stage is healthy at 127.0.0.1:18080; DB and R2 work."
echo "Production traffic STILL targets Northflank. No public ingress was opened."
{
  echo "## Oracle staging completed (not traffic cutover)"
  echo ""
  echo "- ARM64 source commit: $GITHUB_SHA"
  echo "- Service: $APP_SERVICE (enabled)"
  echo "- Local origin: http://127.0.0.1:18080 (loopback only)"
  echo "- Supabase: reachable, migrations current; schema unchanged"
  echo "- Cloudflare R2: authenticated upload/read/delete probe passed"
  echo "- Edge authentication: direct access denied; trusted login succeeded"
  echo "- Public Cloudflare origin: Northflank, unchanged"
} >> "$GITHUB_STEP_SUMMARY"
