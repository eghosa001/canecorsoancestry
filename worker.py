import os

from workers import WorkerEntrypoint, wsgi

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

_application = None


def _binding_text(env, name, default=""):
    value = getattr(env, name, default)
    return str(value or default)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _application

        if _application is None:
            hyperdrive = getattr(self.env, "HYPERDRIVE", None)
            if hyperdrive is None:
                raise RuntimeError("HYPERDRIVE binding is required.")

            connection_string = str(
                getattr(hyperdrive, "connectionString", "") or ""
            )
            if not connection_string:
                raise RuntimeError("HYPERDRIVE connection string is unavailable.")

            os.environ["CLOUDFLARE_DATABASE_URL"] = connection_string
            os.environ["DJANGO_SECRET_KEY"] = _binding_text(
                self.env,
                "DJANGO_SECRET_KEY",
            )
            os.environ["SITE_URL"] = _binding_text(
                self.env,
                "SITE_URL",
                "https://canecorsoancestry.com",
            )
            os.environ["DJANGO_ALLOWED_HOSTS"] = _binding_text(
                self.env,
                "DJANGO_ALLOWED_HOSTS",
                "canecorsoancestry.com,www.canecorsoancestry.com,.workers.dev",
            )
            os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = _binding_text(
                self.env,
                "DJANGO_CSRF_TRUSTED_ORIGINS",
                "https://canecorsoancestry.com,https://www.canecorsoancestry.com,https://*.workers.dev",
            )
            os.environ["MEDIA_MIGRATION_ENABLED"] = _binding_text(
                self.env,
                "MEDIA_MIGRATION_ENABLED",
                "0",
            )

            from django.core.wsgi import get_wsgi_application

            _application = get_wsgi_application()

        return await wsgi.fetch(_application, request, self.env)
