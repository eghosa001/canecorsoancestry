import os
from urllib.parse import urlparse

PROJECT_REF = "wsntfvpcqloqzwgmsfaz"
EXPECTED_HOST = f"db.{PROJECT_REF}.supabase.co"


def main():
    raw = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not raw:
        raise SystemExit("SUPABASE_DATABASE_URL is required.")

    parsed = urlparse(raw)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("SUPABASE_DATABASE_URL must use postgres/postgresql.")
    if parsed.hostname != EXPECTED_HOST:
        raise SystemExit(
            "SUPABASE_DATABASE_URL must be the Supabase Direct connection "
            f"for {PROJECT_REF}, host {EXPECTED_HOST}."
        )
    if (parsed.port or 5432) != 5432:
        raise SystemExit("Supabase Direct connection must use port 5432.")
    if not parsed.username or not parsed.password:
        raise SystemExit(
            "SUPABASE_DATABASE_URL must include the database user and password."
        )
    if parsed.path.rstrip("/") != "/postgres":
        raise SystemExit("SUPABASE_DATABASE_URL must target the postgres database.")

    print("Supabase Direct database URL validated.")


if __name__ == "__main__":
    main()
