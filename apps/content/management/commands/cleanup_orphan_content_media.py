import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from apps.content.models import Summary, Flashcard, ContentLink


class Command(BaseCommand):
    help = "يتتبع ويحذف الملفات اليتيمة غير المرتبطة بقاعدة البيانات داخل مجلد media/content/"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="عرض الملفات اليتيمة دون حذفها فعلياً",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="عدد الملفات المعالجة في الدفعة الواحدة",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        media_root = Path(settings.MEDIA_ROOT).resolve()
        content_media_dir = (media_root / "content").resolve()

        if not content_media_dir.exists():
            self.stdout.write(self.style.SUCCESS("مجلد content داخل MEDIA_ROOT غير موجود. لا توجد ملفات يتيمة."))
            return

        # Build set of registered file names in database
        registered_files = set()

        for path_val in Summary.objects.exclude(file_path="").values_list("file_path", flat=True):
            if path_val:
                registered_files.add((media_root / path_val).resolve())

        for path_val in Flashcard.objects.exclude(front_image_path="").values_list("front_image_path", flat=True):
            if path_val:
                registered_files.add((media_root / path_val).resolve())

        for path_val in Flashcard.objects.exclude(back_image_path="").values_list("back_image_path", flat=True):
            if path_val:
                registered_files.add((media_root / path_val).resolve())

        for path_val in ContentLink.objects.exclude(attached_file_path="").values_list("attached_file_path", flat=True):
            if path_val:
                registered_files.add((media_root / path_val).resolve())

        for path_val in ContentLink.objects.exclude(thumbnail_path="").values_list("thumbnail_path", flat=True):
            if path_val:
                registered_files.add((media_root / path_val).resolve())

        # Scan files on disk
        orphan_files = []
        count = 0

        for root, dirs, files in os.walk(content_media_dir):
            for file_name in files:
                full_file_path = (Path(root) / file_name).resolve()
                if not full_file_path.is_relative_to(media_root):
                    continue

                if full_file_path not in registered_files:
                    orphan_files.append(full_file_path)
                    count += 1
                    if count >= batch_size:
                        break
            if count >= batch_size:
                break

        if not orphan_files:
            self.stdout.write(self.style.SUCCESS("لم يتم العثور على أي ملفات يتيمة."))
            return

        self.stdout.write(f"تم العثور على {len(orphan_files)} ملفاً يتامى.")

        for file_path in orphan_files:
            if dry_run:
                self.stdout.write(f"[DRY-RUN] سيتم حذف: {file_path}")
            else:
                try:
                    os.remove(file_path)
                    self.stdout.write(self.style.SUCCESS(f"تم حذف: {file_path}"))
                except Exception as e:
                    self.stderr.write(f"فشل حذف الملف {file_path}: {e}")
