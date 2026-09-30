import os
import socket
from urllib.parse import quote, urlparse

import psycopg

PROJECT_REF = "wsntfvpcqloqzwgmsfaz"
REGION = "eu-north-1"


def main():
    direct = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    parsed = urlparse(direct)
    password = parsed.password or ""
    database = parsed.path.lstrip("/") or "postgres"

    if not password:
        raise SystemExit("SUPABASE_DATABASE_URL must include the database password.")

    user = f"postgres.{PROJECT_REF}"

    for index in range(16):
        host = f"aws-{index}-{REGION}.pooler.supabase.com"
        try:
            socket.getaddrinfo(host, 5432, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue

        try:
            with psycopg.connect(
                host=host,
                port=5432,
                dbname=database,
                user=user,
                password=password,
                sslmode="require",
                connect_timeout=3,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
        except psycopg.Error:
            continue

        encoded_user = quote(user, safe="")
        encoded_password = quote(password, safe="")
        print(
            f"postgresql://{encoded_user}:{encoded_password}@"
            f"{host}:5432/{quote(database, safe='')}"
        )
        return

    raise SystemExit(
        "Could not discover the Supabase Session Pooler for this project. "
        "Copy the Session pooler URL from Supabase Connect if the pooler layout changes."
    )


if __name__ == "__main__":
    main()
