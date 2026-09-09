from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.imports.services.curriculum_importer import import_curriculum_json_file


class Command(BaseCommand):
    help = "استيراد محتويات المنهج (المواد، الوحدات، الدروس) من مجلد exported_curriculum_json وربطها بالصفوف والأقسام والاترام."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            type=str,
            default=None,
            help="مسار اختياري لملف JSON محدد أو مجلد مخصص.",
        )

    def handle(self, *args, **options):
        custom_path = options.get("path")
        if custom_path:
            target_path = Path(custom_path)
        else:
            target_path = Path(settings.BASE_DIR) / "exported_curriculum_json"

        if not target_path.exists():
            self.stderr.write(self.style.ERROR(f"المجلد أو الملف غير موجود: {target_path}"))
            return

        if target_path.is_file():
            json_files = [target_path]
        else:
            json_files = sorted(list(target_path.glob("*.json")))

        if not json_files:
            self.stderr.write(self.style.WARNING(f"لم يتم العثور على أي ملفات JSON في: {target_path}"))
            return

        self.stdout.write(self.style.SUCCESS(f"🚀 بدء استيراد محتويات المنهج ({len(json_files)} ملف)..."))
        self.stdout.write("-" * 80)

        total_subjects = 0
        total_units = 0
        total_lessons = 0
        failed_files = []

        for idx, json_file in enumerate(json_files, 1):
            try:
                res = import_curriculum_json_file(json_file)
                total_subjects += 1
                total_units += res["units_imported"]
                total_lessons += res["lessons_imported"]

                self.stdout.write(
                    f"[{idx:02d}/{len(json_files):02d}] ✓ {res['subject_name']} ({res['grade']} - {res['section']} | {res['term']}): "
                    f"{res['units_imported']} وحدة, {res['lessons_imported']} درس"
                )
            except Exception as e:
                failed_files.append((json_file.name, str(e)))
                self.stderr.write(self.style.ERROR(f"[{idx:02d}/{len(json_files):02d}] ✗ فشل استيراد {json_file.name}: {e}"))

        self.stdout.write("=" * 80)
        self.stdout.write(
            self.style.SUCCESS(
                f"🎉 اكتمل الاستيراد بنجاح!\n"
                f"📊 الإجمالي: {total_subjects} مادة دراسية | {total_units} وحدة دراسية | {total_lessons} درساً."
            )
        )

        if failed_files:
            self.stdout.write(self.style.WARNING(f"⚠️ تنبيه: تعذر استيراد {len(failed_files)} ملفات:"))
            for fname, err in failed_files:
                self.stdout.write(f"   - {fname}: {err}")
