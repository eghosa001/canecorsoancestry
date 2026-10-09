"""Oracle ARM64 origin; shares Supabase PostgreSQL and Cloudflare R2 with Northflank."""

from config.settings.northflank import *  # noqa: F403,F401

# Applied before Django SecurityMiddleware, including for forged forwarded hosts.
MIDDLEWARE = [  # noqa: F405
    "scripts.oracle_runner.oracle_middleware.OracleEdgeOnlyMiddleware",
    "scripts.oracle_runner.oracle_middleware.OracleMigrationMaintenanceMiddleware",
    *MIDDLEWARE,  # noqa: F405
]
