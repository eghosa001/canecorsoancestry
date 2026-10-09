#!/usr/bin/env bash
# Read-only comparison, never emit connection URLs or passwords.
set -euo pipefail
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" ]] || exit 1
[[ "$GITHUB_REF" == "refs/heads/main" ]] || exit 1
[[ "$(id -un)" == "opc" && "$(uname -m)" == "aarch64" ]] || exit 1
sudo -n systemctl is-active --quiet cca-oracle-staging.service
sudo -n podman exec -i cca-oracle-staging python - <<'PY'
import os
import socket
import statistics
import time
from urllib.parse import urlsplit, unquote
import psycopg

DATABASE_REF = "wsntfvpcqloqzwgmsfaz"
current = urlsplit(os.environ["DATABASE_URL"])
password = unquote(current.password or "")
dbname = unquote(current.path.lstrip("/") or "postgres")
if not password or not dbname:
    raise SystemExit("Missing current database credentials; no changes made")
direct_host = f"db.{DATABASE_REF}.supabase.co"
current_host = current.hostname or ""
if not current_host.endswith(".pooler.supabase.com"):
    raise SystemExit("Unexpected current database connection type; refusing comparison")
print("current_route=session-pooler", flush=True)
print("candidate_route=direct-postgres", flush=True)
try:
    answers = socket.getaddrinfo(direct_host, 5432, type=socket.SOCK_STREAM)
    v6 = any(x[0] == socket.AF_INET6 for x in answers)
    v4 = any(x[0] == socket.AF_INET for x in answers)
except OSError:
    v6 = v4 = False
print(f"direct_dns_ipv6={v6} direct_dns_ipv4={v4}", flush=True)

def run(label, conn_kwargs):
    try:
        start = time.monotonic()
        with psycopg.connect(
            sslmode="require", connect_timeout=6,
            application_name="cca_oracle_transport_probe",
            options="-c default_transaction_read_only=on",
            **conn_kwargs
        ) as conn:
            establish = (time.monotonic() - start) * 1000
            times = []
            with conn.cursor() as cursor:
                for _ in range(8):
                    tick = time.monotonic()
                    cursor.execute("SELECT 1")
                    assert cursor.fetchone()[0] == 1
                    times.append((time.monotonic() - tick) * 1000)
        print(f"{label}_connect_ms={establish:.1f}", flush=True)
        print(f"{label}_sql_median_ms={statistics.median(times):.1f}", flush=True)
        print(f"{label}_sql_min_ms={min(times):.1f}", flush=True)
        print(f"{label}_sql_max_ms={max(times):.1f}", flush=True)
        return statistics.median(times)
    except (OSError, psycopg.Error) as e:
        print(f"{label}_connect_status=unavailable type={type(e).__name__}", flush=True)
        return None

baseline = run("pooler", {
    "host": current_host, "port": current.port or 5432,
    "dbname": dbname, "user": unquote(current.username or ""),
    "password": password,
})
direct = run("direct", {
    "host": direct_host, "port": 5432,
    "dbname": dbname, "user": "postgres", "password": password,
})
if baseline is not None and direct is not None:
    print(f"direct_minus_pooler_ms={direct-baseline:+.1f}", flush=True)
    print("decision=direct-promising" if direct < baseline * 0.70 else "decision=keep-current-pooler", flush=True)
else:
    print("decision=keep-current-pooler", flush=True)
PY
