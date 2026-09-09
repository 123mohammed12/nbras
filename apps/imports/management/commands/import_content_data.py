import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import ContentImportLog, ImportStatus
from apps.imports.services.content_importer import ContentBatchImporter, sources_from_paths


class Command(BaseCommand):
    help = "Validate or import exam, summary, and smart-card JSON through the shared importer."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=Path)
        parser.add_argument("--content-type", choices=["auto", "exams", "summaries", "smart_cards"], default="auto")
        parser.add_argument("--operation", choices=["validate", "upsert", "replace_scope"], default="validate")
        parser.add_argument("--execute", action="store_true", help="Write changes; otherwise preview only.")

    def handle(self, *args, **options):
        missing = [str(path) for path in options["paths"] if not path.exists()]
        if missing:
            raise CommandError(f"Paths not found: {', '.join(missing)}")
        importer = ContentBatchImporter(
            sources_from_paths(options["paths"]),
            requested_type=options["content_type"],
            operation=options["operation"],
        )
        try:
            report = importer.execute() if options["execute"] else importer.preview()
            status = ImportStatus.SUCCEEDED if options["execute"] else ImportStatus.PREVIEWED
        except Exception as exc:
            ContentImportLog.objects.create(
                content_type=options["content_type"] if options["content_type"] != "auto" else "mixed",
                operation=options["operation"], status=ImportStatus.FAILED,
                source_names=[str(path) for path in options["paths"]], errors=[str(exc)],
            )
            raise
        ContentImportLog.objects.create(
            content_type=report.get("content_type", "mixed"), operation=options["operation"], status=status,
            source_names=[str(path) for path in options["paths"]], source_checksum=importer.checksum,
            report=report, errors=report.get("errors", []), warnings=report.get("warnings", []),
        )
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("errors"):
            raise CommandError("Import validation failed; no content was changed.")
