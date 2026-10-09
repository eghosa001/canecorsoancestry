#!/usr/bin/env python3
"""Small, explicit origin switch for the existing Cloudflare Worker.

Authenticated Cloudflare settings are authoritative: never guess the origin
from an unauthenticated health endpoint or fall back silently.
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

PUBLIC_EDGE = "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
NORTHFLANK = "https://web--canecorsoancestry--4w9gl8jxj4yr.code.run"
ORACLE = "http://127.0.0.1:18080"
VPC_SERVICE_ID = "01a11f0b-aa4d-7fd1-840b-8d7c0221f481"

def parse_origin_bindings(payload):
    """Fail closed unless the exact live Worker origin and transport agree.

    The Cloudflare scripts/{script_name}/settings endpoint reports bindings
    as a list; secret values are deliberately never read or printed.
    """
    if not payload.get("success"):
        raise RuntimeError("Cloudflare Workers settings response was unsuccessful")
    settings = payload.get("result")
    if not isinstance(settings, dict):
        raise RuntimeError("Missing Cloudflare Worker settings")
    bindings = settings.get("bindings")
    if not isinstance(bindings, list):
        raise RuntimeError("Missing live Worker bindings")
    names = ("ORIGIN_URL", "ORIGIN_TRANSPORT", "ORIGIN_VPC")
    selected = {}
    for entry in bindings:
        name = entry.get("name")
        if name in names:
            if name in selected:
                raise RuntimeError(f"Duplicate live Worker binding: {name}")
            selected[name] = entry
    origin = selected.get("ORIGIN_URL", {})
    if origin.get("type") != "plain_text":
        raise RuntimeError("ORIGIN_URL must be a plain-text Worker binding")
    value = origin.get("text")
    transport = selected.get("ORIGIN_TRANSPORT")
    vpc = selected.get("ORIGIN_VPC")
    if value == NORTHFLANK and transport is None and vpc is None:
        raise RuntimeError("Northflank is a retired, stale origin and cannot serve Oracle-local production")
    if (value == ORACLE and transport is not None
            and transport.get("type") == "plain_text"
            and transport.get("text") == "private-vpc"
            and vpc is not None
            and vpc.get("type") == "vpc_service"
            and vpc.get("service_id") == VPC_SERVICE_ID):
        return "oracle"
    raise RuntimeError("Live Worker origin, transport or VPC binding is not an approved configuration")


def live_mode():
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not re.fullmatch(r"[0-9a-f]{32}", account) or not token:
        raise RuntimeError("Missing Cloudflare account ID or API token")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{account}"
           "/workers/scripts/canecorsoancestry-site-edge/settings")
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json", "User-Agent": "CCA-Deploy/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Cloudflare Worker settings HTTP {exc.code}; account API permission or availability") from None
    return parse_origin_bindings(payload)

def render(text, mode):
    if mode != "oracle":
        raise ValueError("Oracle private VPC is the only authorized production mode")
    if text.count('name = "canecorsoancestry-site-edge"') != 1:
        raise ValueError("Not the CCA production Worker")
    if text.count('main = "src/site-edge.js"') != 1:
        raise ValueError("Unexpected Worker entrypoint")
    lines = text.splitlines()
    kept = []
    skip_vpc = False
    for line in lines:
        if line.strip() == "[[vpc_services]]":
            skip_vpc = True
            continue
        if skip_vpc and line.startswith("["):
            skip_vpc = False
        if skip_vpc:
            continue
        if line.strip().startswith("ORIGIN_TRANSPORT ="):
            continue
        kept.append(line)
    text = "\n".join(kept).rstrip() + "\n"
    target = ORACLE
    text, count = re.subn(
        r'(?m)^ORIGIN_URL = "[^"]+"$',
        f'ORIGIN_URL = "{target}"\nORIGIN_TRANSPORT = "private-vpc"',
        text,
    )
    if count != 1:
        raise ValueError(f"Expected one ORIGIN_URL, got {count}")
    text += f'\n[[vpc_services]]\nbinding = "ORIGIN_VPC"\nservice_id = "{VPC_SERVICE_ID}"\n'
    return text

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("live-mode")
    r = sub.add_parser("render")
    r.add_argument("--mode", choices=["oracle"], required=True)
    r.add_argument("--config", default="wrangler.site.toml")
    args = p.parse_args()
    if args.action == "live-mode":
        print(live_mode())
    elif args.action == "render":
        path = Path(args.config)
        path.write_text(render(path.read_text(encoding="utf-8"), args.mode), encoding="utf-8")
        print(f"CCA Worker configured for {args.mode}")

if __name__ == "__main__":
    main()
