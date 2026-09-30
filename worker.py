import os

import dj_database_url
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.db import connections
from workers import WorkerEntrypoint, asgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

# Build Django's app registry in Cloudflare's startup phase. The settings module
# intentionally uses Django's dummy database backend here, so startup does not
# import psycopg or read Hyperdrive.
_application = get_asgi_application()
_database_ready = False


def _install_hyperdrive_database(env):
    hyperdrive = getattr(env, "HYPERDRIVE", None)
    if hyperdrive is None:
        raise RuntimeError("HYPERDRIVE binding is required.")

    connection_string = str(
        getattr(hyperdrive, "connectionString", "") or ""
    )
    if not connection_string:
        raise RuntimeError("HYPERDRIVE connection string is unavailable.")

    database = dj_database_url.parse(
        connection_string,
        conn_max_age=0,
    )
    database["CONN_HEALTH_CHECKS"] = False
    database.setdefault("OPTIONS", {})["options"] = (
        "-c search_path=django_app,extensions,public"
    )

    settings.DATABASES["default"] = database
    connections.databases["default"] = database

    # A database wrapper should not be created during Django startup, but clear
    # one defensively if an installed app touched the placeholder connection.
    local_connections = connections._connections
    if hasattr(local_connections, "default"):
        delattr(local_connections, "default")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _database_ready

        if not _database_ready:
            _install_hyperdrive_database(self.env)
            _database_ready = True

        return await asgi.fetch(_application, request, self.env)
