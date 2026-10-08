#!/usr/bin/env bash
# Add a dedicated CCA-only runner without interrupting the existing PULSE runner.
set -euo pipefail
umask 077
REPO_URL="https://github.com/eghosa001/canecorsoancestry"
RUNNER_DIR="${CCA_RUNNER_DIR:-$HOME/actions-runner-cca}"
PULSE_SERVICE="actions.runner.eghosa001-PULSE-CITY.ORACLE.service"

install_runner() {
  if [[ "$(id -u)" -eq 0 || "$(uname -m)" != "aarch64" ]]; then
    echo "Run as the normal opc user on Linux ARM64, not as root." >&2
    exit 1
  fi
  for cmd in curl python3 tar sha256sum sudo; do
    command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 1; }
  done
  if [[ -d "$RUNNER_DIR" && -n "$(ls -A "$RUNNER_DIR")" ]]; then
    echo "Refusing to overwrite existing runner files at $RUNNER_DIR." >&2
    exit 1
  fi
  mkdir -p "$RUNNER_DIR"
  chmod 700 "$RUNNER_DIR"
  cd "$RUNNER_DIR"
  echo "Fetching official GitHub Actions runner ARM64 release ..."
  curl -fsSL --retry 3 https://api.github.com/repos/actions/runner/releases/latest -o runner-release.json
  mapfile -t asset < <(python3 - <<'PY'
import json
with open("runner-release.json", encoding="utf-8") as fp:
    release = json.load(fp)
matches = [a for a in release.get("assets", []) if a.get("name", "").startswith("actions-runner-linux-arm64-") and a.get("name", "").endswith(".tar.gz")]
if len(matches) != 1:
    raise SystemExit("Expected exactly one official Linux ARM64 archive.")
print(matches[0]["browser_download_url"])
print(matches[0].get("digest", ""))
PY
  )
  [[ "${#asset[@]}" == 2 && "${asset[1]}" == sha256:* ]] || {
    echo "Official asset or SHA-256 digest unavailable; refusing unverified install." >&2
    exit 1
  }
  curl -fL --retry 3 "${asset[0]}" -o runner.tar.gz
  printf '%s  runner.tar.gz\n' "${asset[1]#sha256:}" | sha256sum --check
  tar -xzf runner.tar.gz
  rm runner.tar.gz runner-release.json

  echo "Open ${REPO_URL}/settings/actions/runners/new and select Linux/ARM64."
  echo "Paste the short-lived value after --token ONLY at the hidden prompt below."
  echo "Never share the token, private SSH key, or GitHub credentials in chat."
  local registration_token
  read -r -s -p "CCA runner registration token: " registration_token
  echo
  [[ -n "$registration_token" ]] || { echo "Token required." >&2; exit 1; }
  ./config.sh --unattended --url "$REPO_URL" --token "$registration_token" \
    --name CCA-ORACLE --labels cca-oracle --work _work
  unset registration_token
  sudo -n ./svc.sh install "$(id -un)"
  sudo -n ./svc.sh start
  [[ -f .service ]] || { echo "Missing generated systemd service name." >&2; exit 1; }
  local cca_unit
  cca_unit="$(cat .service)"
  [[ "$cca_unit" == *"eghosa001-canecorsoancestry"* ]] || { echo "Wrong repository runner: $cca_unit" >&2; exit 1; }
  sudo -n systemctl is-active --quiet "$cca_unit"
  echo "CCA service active: $cca_unit"
  echo "Next: manually run the 'Oracle repo-only runner' action on the CCA main branch."
  echo "Do NOT stop PULSE until CCA verification passes."
}

retire_pulse() {
  [[ "${2:-}" == "--cca-workflow-passed" ]] || {
    echo "First verify the CCA workflow; then run: bash $0 retire-pulse --cca-workflow-passed" >&2
    exit 1
  }
  [[ -f "$RUNNER_DIR/.service" ]] || { echo "CCA runner service missing." >&2; exit 1; }
  local cca_unit
  cca_unit="$(cat "$RUNNER_DIR/.service")"
  [[ "$cca_unit" == *"eghosa001-canecorsoancestry"* ]] || { echo "Runner not CCA-scoped." >&2; exit 1; }
  sudo -n systemctl is-active --quiet "$cca_unit" || { echo "CCA runner inactive; keeping PULSE running." >&2; exit 1; }
  sudo -n systemctl disable --now "$PULSE_SERVICE"
  if sudo -n systemctl is-active --quiet "$PULSE_SERVICE"; then
    echo "PULSE runner did not stop; check its service." >&2
    exit 1
  fi
  echo "Only the CCA runner service remains active."
  echo "Remove the now-OFFLINE ORACLE runner via PULSE-CITY Settings > Actions > Runners."
}

case "${1:-}" in
  install) install_runner ;;
  retire-pulse) retire_pulse "$@" ;;
  *) echo "Usage: bash $0 install | retire-pulse --cca-workflow-passed" >&2; exit 2 ;;
esac
