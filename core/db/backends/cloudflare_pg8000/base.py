from django_pg8000.base import DatabaseWrapper as Pg8000DatabaseWrapper


class DatabaseWrapper(Pg8000DatabaseWrapper):
    """pg8000 backend tuned for Cloudflare Hyperdrive."""

    def init_connection_state(self):
        super().init_connection_state()
        with self.cursor() as cursor:
            cursor.execute(
                "SET search_path TO django_app, extensions, public"
            )
