import os

import dj_database_url
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.db import connections
from workers import WorkerEntrypoint, asgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

# Cloudflare Python Workers are optimized for ASGI. Build Django's app registry
# during the Worker's startup phase so request CPU is reserved for actual work.
_application = get_asgi_application()
_database_ready = False


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _database_ready

        if not _database_ready:
            hyperdrive = getattr(self.env, "HYPERDRIVE", None)
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

            # Django has initialized, but no ORM query has run yet. Replace the
            # startup placeholder with Hyperdrive before dispatching request 1.
            settings.DATABASES["default"] = database
            connections.settings["default"] = database
            _database_ready = True

        return await asgi.fetch(_application, request, self.env)
