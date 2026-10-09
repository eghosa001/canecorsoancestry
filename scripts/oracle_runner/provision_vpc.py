#!/usr/bin/env python3
"""Provision one CCA Tunnel and narrowly scoped VPC service; print IDs only."""
import argparse
import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}"
TUNNEL_NAME = "cca-oracle-private-vpc"
SERVICE_NAME = "cca-oracle-django-local"

def cloudflare(method, path, payload=None):
    if not ACCOUNT or not TOKEN:
        raise RuntimeError("Cloudflare account ID / API token must be configured")
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        API + path, data=body, method=method,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Cloudflare {method} {path.split('?')[0]} HTTP {exc.code}; check Tunnel and Connectivity Directory permissions") from None
    if not data.get("success"):
        errors = ", ".join(str(e.get("code", "unknown")) for e in data.get("errors", []))
        raise RuntimeError(f"Cloudflare request failed, codes: {errors}")
    return data["result"]

def ensure_tunnel(token_out):
    tunnels = cloudflare("GET", "/cfd_tunnel?per_page=100")
    matches = [t for t in tunnels if t.get("name") == TUNNEL_NAME and not t.get("deleted_at")]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous duplicate CCA tunnels")
    if matches:
        tunnel = matches[0]
        if tunnel.get("config_src") != "cloudflare":
            raise RuntimeError("Existing tunnel is not remotely managed")
    else:
        tunnel = cloudflare("POST", "/cfd_tunnel", {"name": TUNNEL_NAME, "config_src": "cloudflare"})
    tunnel_id = tunnel["id"]
    token = cloudflare("GET", f"/cfd_tunnel/{tunnel_id}/token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Tunnel token unavailable")
    path = Path(token_out)
    path.write_text(token, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(tunnel_id)

def ensure_service(tunnel_id):
    services = cloudflare("GET", "/connectivity/directory/services?per_page=100")
    matches = [s for s in services if s.get("name") == SERVICE_NAME]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous duplicate CCA VPC services")
    if matches:
        service = matches[0]
        host = service.get("host", {})
        if (service.get("type") != "http"
            or host.get("network", {}).get("tunnel_id") != tunnel_id
            or host.get("ipv4") != "127.0.0.1"
            or service.get("http_port") != 18080):
            raise RuntimeError("Existing VPC service points elsewhere; refusing mutation")
    else:
        service = cloudflare("POST", "/connectivity/directory/services", {
            "name": SERVICE_NAME, "type": "http", "http_port": 18080,
            "host": {"ipv4": "127.0.0.1", "network": {"tunnel_id": tunnel_id}},
        })
    print(service["service_id"])

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="task", required=True)
    t = sub.add_parser("tunnel")
    t.add_argument("--token-out", required=True)
    s = sub.add_parser("service")
    s.add_argument("--tunnel-id", required=True)
    h = sub.add_parser("health")
    h.add_argument("--tunnel-id", required=True)
    args = parser.parse_args()
    if args.task == "tunnel":
        ensure_tunnel(args.token_out)
    elif args.task == "service":
        ensure_service(args.tunnel_id)
    else:
        print(cloudflare("GET", f"/cfd_tunnel/{args.tunnel_id}").get("status", "unknown"))

if __name__ == "__main__":
    main()
