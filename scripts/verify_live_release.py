"""Independently attest that Cloudflare serves the current Oracle Django release.

Read-only health checks. During a short post-merge deploy grace period, SHA
mismatch is reported as a warning; after grace it is a failing gate.
"""
import argparse
import json
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HEX_SHA = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_GRACE_SECONDS = 90 * 60


def classify_attestation(payload, expected_sha, *, commit_epoch, now_epoch=None, grace_seconds=DEFAULT_GRACE_SECONDS):
    if not HEX_SHA.fullmatch(expected_sha):
        raise ValueError("Expected release SHA must be a 40-character lowercase Git SHA.")
    if not isinstance(payload, dict):
        raise ValueError("Live health response must be a JSON object.")
    if payload.get("status") != "ok" or payload.get("service") != "canecorsoancestry":
        return "failure", "The live application health response is not healthy."
    if payload.get("database_backend") != "oracle-local":
        return "failure", "The live application is not verified against Oracle-local PostgreSQL."
    current = payload.get("release")
    if current == expected_sha:
        return "success", "Live Oracle Django release matches current main."
    now = time.time() if now_epoch is None else now_epoch
    age = max(0, now - commit_epoch)
    if age < grace_seconds:
        return "warning", (
            "Live Django release does not yet match main; deploy grace period "
            f"remaining: {int(grace_seconds - age)} seconds. "
            f"Expected {expected_sha}; observed {current or '<missing>'}."
        )
    return "failure", (
        f"Live Django release is stale after deploy grace period. "
        f"Expected {expected_sha}; observed {current or '<missing>'}."
    )


def fetch_health(base_url):
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.netloc or url.username or url.password:
        raise ValueError("The production base URL must be an HTTPS site without credentials.")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError("The production base URL must have no path, query or fragment.")
    request = Request(
        base_url.rstrip("/") + "/healthz/",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "CCA-Release-Attestation/1.0",
        },
    )
    with urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"Live health returned HTTP {response.status}.")
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--commit-epoch", type=int, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        payload = fetch_health(args.base_url)
        status, message = classify_attestation(
            payload, args.expected_sha, commit_epoch=args.commit_epoch
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"::error::Release attestation unavailable: {exc}")
        raise SystemExit(1) from exc
    prefix = "::warning::" if status == "warning" else "::error::" if status == "failure" else ""
    print(prefix + message)
    if status == "failure":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
