import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.db import connections
from workers import WorkerEntrypoint, wsgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

_application = get_wsgi_application()
_database_ready = False


def _install_hyperdrive_database(env):
    hyperdrive = getattr(env, "HYPERDRIVE", None)
    if hyperdrive is None:
        raise RuntimeError("HYPERDRIVE binding is required.")

    required = {
        "HOST": str(getattr(hyperdrive, "host", "") or ""),
        "PORT": str(getattr(hyperdrive, "port", "") or ""),
        "USER": str(getattr(hyperdrive, "user", "") or ""),
        "PASSWORD": str(getattr(hyperdrive, "password", "") or ""),
        "NAME": str(getattr(hyperdrive, "database", "") or ""),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Hyperdrive binding is missing: " + ", ".join(missing))

    database = {
        "ENGINE": "core.db.backends.cloudflare_pg8000",
        **required,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {"ssl_context": False},
    }

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

        if not _database_ready:
            _install_hyperdrive_database(self.env)
            _database_ready = True

        return await wsgi.fetch(_application, request, self.env)
