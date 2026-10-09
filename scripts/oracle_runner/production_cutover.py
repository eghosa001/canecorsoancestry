#!/usr/bin/env python3
"""Manual, reversible Cloudflare Worker origin switch, no VM SSH needed."""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from scripts.oracle_runner.edge_origin_mode import (
    NORTHFLANK, ORACLE, PUBLIC_EDGE, live_mode, render,
)

CANDIDATE = "https://canecorsoancestry-oracle-candidate.aighewieghosa111.workers.dev"
CONFIG = Path("wrangler.site.toml")


def open_checked(url, *, headers=None, data=None, cookie_file=None, expected=200):
    """Use curl for live endpoint smoke checks (Python urllib is WAF-blocked).

    No credential values or response bodies are logged.
    """
    cmd = ["curl", "-sS", "--connect-timeout", "5", "--max-time", "20",
           "--output", "-", "--write-out", "\n__CCA_STATUS__%{http_code}"]
    for name, value in (headers or {}).items():
        cmd.extend(["-H", f"{name}: {value}"])
    if cookie_file:
        cmd.extend(["--cookie", cookie_file, "--cookie-jar", cookie_file])
    if data is not None:
        cmd.extend(["--data-binary", "@-"])
    cmd.append(url)
    process = subprocess.run(
        cmd, input=data, capture_output=True, timeout=25, check=False,
    )
    if process.returncode:
        raise RuntimeError(f"HTTP smoke request failed for {url}: curl exit {process.returncode}")
    body, marker, status = process.stdout.rpartition(b"\n__CCA_STATUS__")
    if not marker or status.decode("ascii").strip() != str(expected):
        raise RuntimeError(f"Unexpected HTTP response for {url}: {status!r}")
    return body

def preflight_candidate(secret):
    headers = {"X-CCA-Candidate-Test": secret}
    ready = json.loads(open_checked(CANDIDATE + "/__edge/auth-ready", headers=headers))
    if not ready.get("ready"):
        raise RuntimeError("Oracle auth readiness returned false")
    for path in ["/", "/accounts/login/", "/pedigrees/virtual-mating/",
                 "/dogs/suggestions/?q=&browse=1&sex=male",
                 "/static/core/site.css"]:
        body = open_checked(CANDIDATE + path, headers=headers)
        if not body:
            raise RuntimeError(f"Empty candidate response {path}")
        print(f"Oracle candidate {path}: PASS")
    # A deliberately invalid login is a safe way to verify real CSRF/form
    # submission before exposing Oracle to production logins.
    with tempfile.NamedTemporaryFile(prefix="cca-canary-cookie-", delete=False) as f:
        cookie_path = f.name
    try:
        return _check_csrf_login(headers, cookie_path)
    finally:
        Path(cookie_path).unlink(missing_ok=True)


def _check_csrf_login(headers, cookie_path):
    html = open_checked(CANDIDATE + "/accounts/login/", headers=headers, cookie_file=cookie_path)
    match = re.search(rb'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
    if match is None:
        raise RuntimeError("Candidate login CSRF token missing")
    post = urllib.parse.urlencode({
        "csrfmiddlewaretoken": match.group(1).decode(),
        "username": "cca-cutover-canary-nonexistent",
        "password": "invalid-password-only",
    }).encode()
    answer = open_checked(
        CANDIDATE + "/accounts/login/", cookie_file=cookie_path, data=post,
        headers={**headers, "Origin": PUBLIC_EDGE,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    if b"CSRF verification failed" in answer or b"Forbidden (403)" in answer:
        raise RuntimeError("Candidate login POST blocked by CSRF")
    print("Oracle login POST and CSRF: PASS")


def configure(mode, cache_version):
    text = CONFIG.read_text(encoding="utf-8")
    # Only one cache version belongs inside [vars]; remove old if present.
    text = re.sub(r'(?m)^EDGE_CACHE_VERSION = "[^"]+"\n', "", text)
    text = render(text, mode)
    marker = f'ORIGIN_URL = "{ORACLE if mode == "oracle" else NORTHFLANK}"'
    if text.count(marker) != 1:
        raise RuntimeError("Origin marker missing in Cloudflare Worker config")
    text = text.replace(marker, marker + f'\nEDGE_CACHE_VERSION = "{cache_version}"')
    CONFIG.write_text(text, encoding="utf-8")


def deploy(secret_file):
    subprocess.run(["node", "--check", "src/site-edge.js"], check=True)
    subprocess.run(
        ["npx", "--yes", "wrangler@4", "deploy", "--config", str(CONFIG),
         "--secrets-file", secret_file],
        check=True, timeout=150,
    )


def verify(expected, cache_version):
    for attempt in range(18):
        try:
            health = json.loads(open_checked(PUBLIC_EDGE + "/__edge/health"))
            if (health.get("origin") == expected and
                    health.get("cache_version") == cache_version):
                break
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(3)
    else:
        raise RuntimeError("Production edge origin/version mismatch after deploy")

    ready = json.loads(open_checked(PUBLIC_EDGE + "/__edge/auth-ready"))
    if not ready.get("ready"):
        raise RuntimeError("Live auth readiness is false")
    for path in ("/", "/accounts/login/", "/pedigrees/virtual-mating/",
                 "/static/core/site.css"):
        body = open_checked(PUBLIC_EDGE + path, headers={"Accept": "text/html"})
        if not body:
            raise RuntimeError(f"Live route {path} is empty")
        if path == "/" and b'data-ui-version="customer-v49"' not in body:
            raise RuntimeError("Live homepage UI marker missing")
        print(f"Production {path}: PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("oracle", "northflank"))
    parser.add_argument("--cache-version", required=True)
    args = parser.parse_args()
    secret = os.environ.get("DJANGO_SECRET_KEY", "")
    if not secret or not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("Cloudflare token and Django origin secret are required")
    before = live_mode()
    print(f"Live origin before operation: {before}")
    if before == args.mode:
        print("Already in requested mode; no production change needed.")
        return
    if args.mode == "oracle":
        preflight_candidate(secret)

    with tempfile.NamedTemporaryFile(mode="w", prefix="cca-worker-secret-",
                                     suffix=".json", delete=False) as handle:
        secret_path = handle.name
        os.chmod(secret_path, 0o600)
        json.dump({"ORIGIN_EDGE_SECRET": secret}, handle)
    try:
        configure(args.mode, args.cache_version)
        try:
            deploy(secret_path)
            verify(ORACLE if args.mode == "oracle" else NORTHFLANK,
                   args.cache_version)
        except Exception as error:
            print(f"Cutover validation failed: {type(error).__name__}; restoring {before}")
            rollback_version = args.cache_version + "-rollback"
            try:
                configure(before, rollback_version)
                deploy(secret_path)
                verify(ORACLE if before == "oracle" else NORTHFLANK, rollback_version)
                print(f"Previous origin {before} restored.")
            except Exception:
                print("EMERGENCY: Automatic rollback failed; inspect Cloudflare Worker.")
                raise
            raise
        print(f"Production origin successfully changed: {before} -> {args.mode}")
        print("Northflank remains running for rollback.")
    finally:
        Path(secret_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
