import json

from django.core.management.base import BaseCommand, CommandError

from apps.imports.services.mock_review_importer import MockReviewImporter


class Command(BaseCommand):
    help = "Preview, publish, or safely remove the idempotent AR-05 Mock review blueprint."

    def add_arguments(self, parser):
        parser.add_argument("--subject-id", default="3s_sci_quran")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--remove", action="store_true")

    def handle(self, *args, **options):
        if options["execute"] and options["remove"]:
            raise CommandError("Choose either --execute or --remove.")
        importer = MockReviewImporter(subject_id=options["subject_id"])
        report = (
            importer.remove() if options["remove"]
            else importer.execute() if options["execute"]
            else importer.preview()
        )
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
