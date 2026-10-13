"""Validate a deployment domain before it reaches canonical/CSRF settings."""
import re
import sys
from urllib.parse import urlsplit

DEFAULT_SITE = "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")

def public_site(raw=""):
    text = (raw or DEFAULT_SITE).strip()
    parts = urlsplit(text)
    host = parts.hostname or ""
    labels = host.split(".")
    if (
        parts.scheme != "https"
        or not host or len(host) > 253 or len(labels) < 2
        or any(not LABEL.fullmatch(label) for label in labels)
        or parts.username is not None or parts.password is not None
        or parts.port is not None or parts.netloc != host
        or parts.path not in ("", "/")
        or parts.query or parts.fragment
    ):
        raise ValueError("Public site must be a bare HTTPS hostname without a port, path, credentials or query")
    return f"https://{host}", host

if __name__ == "__main__":
    try:
        print(public_site(sys.argv[1] if len(sys.argv) > 1 else "")[0])
    except ValueError as exc:
        raise SystemExit(str(exc))
