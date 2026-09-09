from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.imports.services.curriculum_importer import import_curriculum_json_file


class Command(BaseCommand):
    help = "Import curriculum JSON exports from exported_curriculum_json directory."

    def handle(self, *args, **options):
        json_dir = Path(settings.BASE_DIR) / "exported_curriculum_json"
        if not json_dir.exists():
            self.stderr.write(self.style.ERROR(f"Directory not found: {json_dir}"))
            return

        json_files = list(json_dir.glob("*.json"))
        self.stdout.write(self.style.SUCCESS(f"Found {len(json_files)} JSON curriculum files to import..."))

        total_units = 0
        total_lessons = 0

        for json_file in json_files:
            try:
                res = import_curriculum_json_file(json_file)
                total_units += res["units_imported"]
                total_lessons += res["lessons_imported"]
                self.stdout.write(f"Imported {res['subject']}: {res['units_imported']} units, {res['lessons_imported']} lessons.")
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to import {json_file.name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Completed! Total units: {total_units}, Total lessons: {total_lessons}."))
