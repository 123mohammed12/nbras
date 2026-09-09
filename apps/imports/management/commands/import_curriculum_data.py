from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.imports.services.curriculum_importer import import_curriculum_json_file


class Command(BaseCommand):
    help = "Imports all curriculum JSON files from exported_curriculum_json into the database."

    def handle(self, *args, **options):
        json_dir = Path(settings.BASE_DIR) / "exported_curriculum_json"
        if not json_dir.exists():
            self.stderr.write(self.style.ERROR(f"Directory not found: {json_dir}"))
            return

        json_files = sorted(json_dir.glob("*.json"))
        if not json_files:
            self.stdout.write(self.style.WARNING("No JSON files found in exported_curriculum_json."))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(json_files)} JSON files to import..."))

        total_units = 0
        total_lessons = 0

        for file_path in json_files:
            try:
                res = import_curriculum_json_file(file_path)
                u_cnt = res["units_imported"]
                l_cnt = res["lessons_imported"]
                total_units += u_cnt
                total_lessons += l_cnt
                self.stdout.write(
                    self.style.SUCCESS(
                        f" Successfully imported '{file_path.name}' -> Subject: {res['subject']} ({u_cnt} units, {l_cnt} lessons)"
                    )
                )
            except Exception as e:
                self.stderr.write(self.style.ERROR(f" Error importing '{file_path.name}': {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\n Import completed successfully! Total imported: {len(json_files)} subjects, {total_units} units, {total_lessons} lessons."
            )
        )
