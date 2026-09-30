import asyncio
import os

import dj_database_url
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.db import connections
from workers import WorkerEntrypoint, wsgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")
# Python Workers invoke the WSGI bridge from an async event loop but do not
# provide native threads. This application is intentionally serialized below,
# so Django's synchronous ORM can safely run in that single request lane.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

_application = get_wsgi_application()
_database_ready = False
_request_lock = asyncio.Lock()


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

    configured = connections.configure_settings({"default": database})
    settings.DATABASES["default"] = configured["default"]
    connections._settings = configured
    connections.__dict__.pop("settings", None)

    local_connections = connections._connections
    if hasattr(local_connections, "default"):
        delattr(local_connections, "default")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _database_ready

        # Cloudflare's Python database docs require synchronous DB operations
        # to be serialized. Since Django's WSGI stack may touch the ORM anywhere
        # in a request, serialize the full WSGI dispatch rather than individual
        # cursor calls.
        async with _request_lock:
            if not _database_ready:
                _install_hyperdrive_database(self.env)
                _database_ready = True

            return await wsgi.fetch(_application, request, self.env)
