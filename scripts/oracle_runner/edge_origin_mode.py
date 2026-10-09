#!/usr/bin/env python3
"""Small, explicit origin switch for the existing Cloudflare Worker.

The public Worker self-reports its active origin via /__edge/health; automatic
deployments must preserve that choice. No implicit fallbacks on failure.
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

PUBLIC_EDGE = "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
NORTHFLANK = "https://web--canecorsoancestry--4w9gl8jxj4yr.code.run"
ORACLE = "http://127.0.0.1:18080"
VPC_SERVICE_ID = "01a11f0b-aa4d-7fd1-840b-8d7c0221f481"

def live_mode():
    with urllib.request.urlopen(PUBLIC_EDGE + "/__edge/health", timeout=12) as response:
        if response.status != 200:
            raise RuntimeError("Cloudflare edge health unavailable")
        payload = json.load(response)
    if payload.get("service") != "site-edge":
        raise RuntimeError("Unexpected Cloudflare Worker health payload")
    origin = payload.get("origin")
    if origin == NORTHFLANK:
        return "northflank"
    if origin == ORACLE:
        return "oracle"
    raise RuntimeError(f"Unexpected live origin {origin!r}; refusing implicit cutover")

def render(text, mode):
    if mode not in ("oracle", "northflank"):
        raise ValueError("Invalid origin mode")
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
    target = ORACLE if mode == "oracle" else NORTHFLANK
    text, count = re.subn(
        r'(?m)^ORIGIN_URL = "[^"]+"$',
        f'ORIGIN_URL = "{target}"' + ('\nORIGIN_TRANSPORT = "private-vpc"' if mode == "oracle" else ""),
        text,
    )
    if count != 1:
        raise ValueError(f"Expected one ORIGIN_URL, got {count}")
    if mode == "oracle":
        text += f'\n[[vpc_services]]\nbinding = "ORIGIN_VPC"\nservice_id = "{VPC_SERVICE_ID}"\n'
    return text

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("live-mode")
    r = sub.add_parser("render")
    r.add_argument("--mode", choices=["oracle", "northflank"], required=True)
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
