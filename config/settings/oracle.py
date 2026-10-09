"""Oracle ARM64 origin; shares Supabase PostgreSQL and Cloudflare R2 with Northflank."""

from .northflank import *  # noqa: F403,F401

# Applied before Django SecurityMiddleware, including for forged forwarded hosts.
MIDDLEWARE = [  # noqa: F405
    "config.oracle_middleware.OracleEdgeOnlyMiddleware",
    *MIDDLEWARE,  # noqa: F405
]
