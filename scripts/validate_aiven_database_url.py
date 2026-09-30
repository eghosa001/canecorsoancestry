import os
from urllib.parse import parse_qs, urlparse


def main():
    raw = os.environ.get("AIVEN_DATABASE_URL", "").strip()
    if not raw:
        raise SystemExit("AIVEN_DATABASE_URL is required.")

    parsed = urlparse(raw)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("AIVEN_DATABASE_URL must use postgres/postgresql.")
    if not parsed.hostname or not parsed.hostname.endswith(".aivencloud.com"):
        raise SystemExit("AIVEN_DATABASE_URL must point to an Aiven PostgreSQL host.")
    if not parsed.username or not parsed.password:
        raise SystemExit("AIVEN_DATABASE_URL must include username and password.")
    if not parsed.path or parsed.path == "/":
        raise SystemExit("AIVEN_DATABASE_URL must include a database name.")

    sslmode = parse_qs(parsed.query).get("sslmode", [""])[0]
    if sslmode and sslmode not in {"require", "verify-ca", "verify-full"}:
        raise SystemExit("Aiven connections must use TLS (sslmode=require or stronger).")

    print("Aiven PostgreSQL URL validated.")


if __name__ == "__main__":
    main()
