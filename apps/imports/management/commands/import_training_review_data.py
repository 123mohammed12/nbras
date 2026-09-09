import json

from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import ContentImportLog, ImportStatus
from apps.imports.services.training_review_importer import TrainingReviewImporter


class Command(BaseCommand):
    help = "Preview, import, or remove the identifiable AR-03 Training review dataset."

    def add_arguments(self, parser):
        parser.add_argument("--subject-id", default="3s_sci_quran")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--remove", action="store_true")

    def handle(self, *args, **options):
        if options["execute"] and options["remove"]:
            raise CommandError("Choose either --execute or --remove.")
        importer = TrainingReviewImporter(subject_id=options["subject_id"])
        if options["remove"]:
            report = importer.remove()
        elif options["execute"]:
            report = importer.execute()
        else:
            report = importer.preview()
        ContentImportLog.objects.create(
            content_type="mixed",
            operation="replace_scope" if options["remove"] else "upsert",
            status=(
                ImportStatus.SUCCEEDED
                if options["execute"] or options["remove"]
                else ImportStatus.PREVIEWED
            ),
            source_names=[
                "published curriculum summaries",
                "apps.imports.services.training_review_importer",
            ],
            source_checksum=report.get("dataset", ""),
            report=report,
        )
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
