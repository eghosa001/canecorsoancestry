"""Validated optional commercial domain configuration; no DNS or traffic cutover."""
import re
from urllib.parse import urlsplit

PREVIEW_SITE = "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

def canonical_site(value=""):
    requested = (value or PREVIEW_SITE).strip()
    parsed = urlsplit(requested)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/") or parsed.port is not None):
        raise ValueError("Canonical site must be an HTTPS DNS hostname with no path/query/port")
    host = parsed.hostname.lower()
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Canonical site contains an invalid DNS hostname")
    return "https://" + host

def host_settings(value=""):
    root = canonical_site(value)
    primary = root.removeprefix("https://")
    preview = PREVIEW_SITE.removeprefix("https://")
    hosts = ",".join(dict.fromkeys((primary, preview, "127.0.0.1", "localhost")))
    origins = ",".join(dict.fromkeys((root, PREVIEW_SITE)))
    return root, hosts, origins
