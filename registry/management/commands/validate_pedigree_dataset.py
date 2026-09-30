import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from registry.import_validation import DatasetValidationError, validate_records


class Command(BaseCommand):
    help = "Validate a pedigree JSON dataset without writing any database records."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--strict-warnings", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.exists():
            raise CommandError(f"Source file not found: {source}")

        raw = source.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read source JSON: {exc}") from exc

        try:
            result = validate_records(payload.get("dogs"))
        except DatasetValidationError as exc:
            raise CommandError(str(exc)) from exc

        digest = hashlib.sha256(raw).hexdigest()
        self.stdout.write(
            self.style.SUCCESS(
                f"Validated {result['record_count']} pedigree records; "
                f"{result['registration_count']} registrations; sha256={digest}"
            )
        )
        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        if options["strict_warnings"] and result["warnings"]:
            raise CommandError(
                f"Dataset has {len(result['warnings'])} warning(s)."
            )
