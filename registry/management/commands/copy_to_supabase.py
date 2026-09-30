import io
import os
import tempfile
from urllib.parse import urlparse

import dj_database_url
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


TARGET_ALIAS = "supabase"
COPY_LABELS = ("auth.group", "auth.user", "sessions.session", "admin.logentry", "accounts", "registry")
SKIP_MODELS = {
    ("auth", "permission"),
}


def _target_database():
    url = os.getenv("SUPABASE_DATABASE_URL", "").strip()
    if not url:
        raise CommandError("SUPABASE_DATABASE_URL is required.")

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    project_ref = os.getenv("SUPABASE_PROJECT_REF", "").strip().lower()
    if not (
        host.endswith(".supabase.co")
        or host.endswith(".pooler.supabase.com")
    ):
        raise CommandError("SUPABASE_DATABASE_URL must point to Supabase.")
    if project_ref and project_ref not in url.lower():
        raise CommandError(
            "SUPABASE_DATABASE_URL does not match SUPABASE_PROJECT_REF."
        )

    database = dj_database_url.parse(url, conn_max_age=0)
    options = database.setdefault("OPTIONS", {})
    options["sslmode"] = os.getenv("DJANGO_DB_SSLMODE", "require")
    schema = os.getenv("DJANGO_DB_SCHEMA", "django_app").strip()
    options["options"] = f"-c search_path={schema},extensions,public"
    database["CONN_HEALTH_CHECKS"] = True
    return database


def _install_target_alias():
    database = _target_database()
    settings.DATABASES[TARGET_ALIAS] = database
    connections.databases[TARGET_ALIAS] = database
    return database


def _copied_models():
    selected = []
    allowed_apps = {"accounts", "registry"}
    user_model = get_user_model()
    group_model = apps.get_model("auth", "Group")
    session_model = apps.get_model("sessions", "Session")
    log_entry_model = apps.get_model("admin", "LogEntry")
    for model in apps.get_models():
        key = (model._meta.app_label, model._meta.model_name)
        if key in SKIP_MODELS or model._meta.proxy or not model._meta.managed:
            continue
        if (
            model is user_model
            or model is group_model
            or model is session_model
            or model is log_entry_model
            or model._meta.app_label in allowed_apps
        ):
            selected.append(model)
    return selected


class Command(BaseCommand):
    help = (
        "Copy canonical Django production data from the current default database "
        "to the configured Supabase database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Flush copied application data from Supabase before loading.",
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Only compare source/target model counts.",
        )

    def handle(self, *args, **options):
        _install_target_alias()

        call_command(
            "migrate",
            database=TARGET_ALIAS,
            interactive=False,
            verbosity=max(0, options["verbosity"] - 1),
        )

        if options["verify_only"]:
            self._verify()
            return

        target_has_data = any(
            model._default_manager.using(TARGET_ALIAS).exists()
            for model in _copied_models()
        )
        if target_has_data and not options["replace"]:
            raise CommandError(
                "Supabase already contains application data. "
                "Use --replace only after confirming the target is disposable."
            )

        if target_has_data:
            call_command(
                "flush",
                database=TARGET_ALIAS,
                interactive=False,
                verbosity=max(0, options["verbosity"] - 1),
            )

        buffer = io.StringIO()
        call_command(
            "dumpdata",
            *COPY_LABELS,
            database="default",
            format="json",
            use_natural_foreign_keys=True,
            use_base_manager=True,
            stdout=buffer,
            verbosity=0,
        )

        payload = buffer.getvalue()
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as fixture:
            fixture.write(payload)
            fixture_path = fixture.name

        try:
            call_command(
                "loaddata",
                fixture_path,
                database=TARGET_ALIAS,
                verbosity=max(0, options["verbosity"] - 1),
            )
        finally:
            try:
                os.unlink(fixture_path)
            except FileNotFoundError:
                pass

        self._verify()
        self.stdout.write(self.style.SUCCESS("Supabase data copy verified."))

    def _verify(self):
        mismatches = []
        checked = 0
        for model in _copied_models():
            source_count = model._default_manager.using("default").count()
            target_count = model._default_manager.using(TARGET_ALIAS).count()
            checked += 1
            if source_count != target_count:
                mismatches.append(
                    f"{model._meta.label}: {source_count} != {target_count}"
                )

        if mismatches:
            raise CommandError(
                "Supabase verification failed: " + "; ".join(mismatches)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {checked} model counts against Supabase."
            )
        )
