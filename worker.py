import os

import dj_database_url
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.db import connections
from workers import WorkerEntrypoint, wsgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

# Build Django during Cloudflare startup while settings use the dummy database
# backend. WSGI avoids Django/asgiref thread creation, which Python Workers do
# not support for this synchronous application.
_application = get_wsgi_application()
_database_ready = False


def _install_hyperdrive_database(env):
    hyperdrive = getattr(env, "HYPERDRIVE", None)
    if hyperdrive is None:
        raise RuntimeError("HYPERDRIVE binding is required.")

    connection_string = str(getattr(hyperdrive, "connectionString", "") or "")
    if not connection_string:
        raise RuntimeError("HYPERDRIVE connection string is unavailable.")

    database = dj_database_url.parse(connection_string, conn_max_age=0)
    database["CONN_HEALTH_CHECKS"] = False
    database.setdefault("OPTIONS", {})["options"] = (
        "-c search_path=django_app,extensions,public"
    )

    settings.DATABASES["default"] = database
    connections.databases["default"] = database

    local_connections = connections._connections
    if hasattr(local_connections, "default"):
        delattr(local_connections, "default")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _database_ready

        if not _database_ready:
            _install_hyperdrive_database(self.env)
            _database_ready = True

        return await wsgi.fetch(_application, request, self.env)
