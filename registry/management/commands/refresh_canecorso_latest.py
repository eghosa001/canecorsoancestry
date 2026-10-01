from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Refresh CaneCorsoPedigree latest additions."

    def handle(self, *args, **options):
        self.stdout.write("No changes.")
