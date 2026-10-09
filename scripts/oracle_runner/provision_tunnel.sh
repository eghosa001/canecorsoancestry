#!/usr/bin/env bash
# Outbound-only Cloudflare Tunnel; no changes to public firewall/origin.
set -euo pipefail
umask 077

[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" ]] || exit 1
[[ "$GITHUB_REF" == "refs/heads/main" ]] || exit 1
[[ "$(uname -m)" == "aarch64" && "$(id -un)" == "opc" ]] || exit 1
sudo -n true
for name in CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID; do
  [[ -n "$(printenv "$name" || true)" ]] || { echo "::error::Missing $name"; exit 1; }
done

curl --connect-timeout 3 --max-time 10 -fsS http://127.0.0.1:18080/healthz/ >/dev/null

token_file="$(mktemp)"
release_file="$(mktemp)"
binary_file="$(mktemp)"
unit_file="$(mktemp)"
trap 'rm -f "$token_file" "$release_file" "$binary_file" "$unit_file"' EXIT

tunnel_id="$(python3 scripts/oracle_runner/provision_vpc.py tunnel --token-out "$token_file")"
[[ "$tunnel_id" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "::error::Invalid Cloudflare tunnel ID"; exit 1; }
echo "tunnel_id=$tunnel_id" >> "$GITHUB_OUTPUT"
echo "Private Cloudflare Tunnel registered: $tunnel_id"

if [[ ! -x /usr/local/bin/cca-cloudflared ]]; then
  curl --retry 3 -fsSL https://api.github.com/repos/cloudflare/cloudflared/releases/latest -o "$release_file"
  mapfile -t asset < <(python3 - "$release_file" <<'PY'
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
assets = [a for a in release.get("assets", []) if a.get("name") == "cloudflared-linux-arm64"]
if len(assets) != 1 or not assets[0].get("digest", "").startswith("sha256:"):
    raise SystemExit("No verified cloudflared ARM64 asset")
print(assets[0]["browser_download_url"])
print(assets[0]["digest"].split(":", 1)[1])
PY
  )
  [[ "${#asset[@]}" == 2 ]] || exit 1
  curl --retry 3 -fsSL "${asset[0]}" -o "$binary_file"
  printf '%s  %s\n' "${asset[1]}" "$binary_file" | sha256sum -c -
  sudo -n install -o root -g root -m 755 "$binary_file" /usr/local/bin/cca-cloudflared
fi

sudo -n install -d -m 700 /etc/cca
sudo -n install -o root -g root -m 600 "$token_file" /etc/cca/oracle-tunnel.token
cat > "$unit_file" <<'UNIT'
[Unit]
Description=CCA Oracle private Cloudflare VPC Tunnel
After=network-online.target cca-oracle-staging.service
Wants=network-online.target
Requires=cca-oracle-staging.service

[Service]
Type=simple
DynamicUser=yes
LoadCredential=tunnel-token:/etc/cca/oracle-tunnel.token
ExecStart=/usr/local/bin/cca-cloudflared --no-autoupdate tunnel run --token-file %d/tunnel-token
Restart=always
RestartSec=5
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
UNIT
sudo -n install -o root -g root -m 644 "$unit_file" /etc/systemd/system/cca-cloudflared-vpc.service
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now cca-cloudflared-vpc.service
sudo -n systemctl is-active --quiet cca-cloudflared-vpc.service

for attempt in $(seq 1 24); do
  status="$(python3 scripts/oracle_runner/provision_vpc.py health --tunnel-id "$tunnel_id")"
  if [[ "$status" == "healthy" ]]; then
    echo "Cloudflare private tunnel: healthy"
    {
      echo "## CCA Oracle Tunnel"
      echo "- Tunnel: $tunnel_id"
      echo "- Status: healthy"
      echo "- New inbound web ports: none"
      echo "- GitHub Actions Oracle runner: unchanged"
    } >> "$GITHUB_STEP_SUMMARY"
    exit 0
  fi
  sleep 3
done
echo "::error::Tunnel did not become healthy. Check journalctl -u cca-cloudflared-vpc."
exit 1
