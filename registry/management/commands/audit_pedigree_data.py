import json

from django.core.management.base import BaseCommand, CommandError

from registry.data_quality import full_quality_report


class Command(BaseCommand):
    help = "Audit canonical pedigree integrity, provenance coverage and moderation health."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--fail-on-critical", action="store_true")
        parser.add_argument("--sample-limit", type=int, default=12)

    def handle(self, *args, **options):
        report = full_quality_report(
            sample_limit=max(1, min(options["sample_limit"], 100))
        )
        if options["as_json"]:
            serializable = {
                "counts": report["counts"],
                "source_coverage_percent": round(
                    report["source_coverage_percent"], 2
                ),
                "pedigree_linkage_percent": round(
                    report["pedigree_linkage_percent"], 2
                ),
                "critical_count": report["critical_count"],
                "cycles": [
                    [str(item) for item in cycle]
                    for cycle in report["cycles"]
                ],
            }
            self.stdout.write(json.dumps(serializable, sort_keys=True))
        else:
            self.stdout.write("Cane Corso Ancestry data-quality audit")
            for key, value in sorted(report["counts"].items()):
                self.stdout.write(f"- {key}: {value}")
            self.stdout.write(
                f"- source_coverage_percent: {report['source_coverage_percent']:.1f}"
            )
            self.stdout.write(
                f"- pedigree_linkage_percent: {report['pedigree_linkage_percent']:.1f}"
            )
            self.stdout.write(f"- critical_count: {report['critical_count']}")

        if options["fail_on_critical"] and report["critical_count"]:
            raise CommandError(
                f"Data-quality audit found {report['critical_count']} critical issue(s)."
            )
