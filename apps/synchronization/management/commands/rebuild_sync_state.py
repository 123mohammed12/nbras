import hashlib
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.curriculum.models import Grade, Section, Subject, Unit, Lesson
from apps.content.models import Summary, FlashcardDeck, ContentLink, LessonExplanation
from apps.synchronization.models import SyncChange, SyncChangeAction

logger = logging.getLogger("synchronization.rebuild")


class Command(BaseCommand):
    help = "Rebuild initial sync state and calculate resource checksums/versions idempotently."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Rebuild sync state for all resources.")
        parser.add_argument("--grade", type=str, help="Filter by Grade ID.")
        parser.add_argument("--section", type=str, help="Filter by Section ID.")
        parser.add_argument("--subject", type=str, help="Filter by Subject ID.")
        parser.add_argument("--resource-type", type=str, help="Filter by specific resource type.")
        parser.add_argument("--dry-run", action="store_true", help="Simulate rebuild without writing to DB.")
        parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing.")
        parser.add_argument("--resume-from", type=int, default=0, help="Resume from sequence offset.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        resource_type_filter = options.get("resource_type")
        grade_id = options.get("grade")
        subject_id = options.get("subject")

        self.stdout.write(self.style.NOTICE(f"Starting rebuild_sync_state (dry_run={dry_run})..."))

        models_to_process = [
            ("grade", Grade),
            ("section", Section),
            ("subject", Subject),
            ("unit", Unit),
            ("lesson", Lesson),
            ("summary", Summary),
            ("flashcard_deck", FlashcardDeck),
            ("content_link", ContentLink),
            ("lesson_explanation", LessonExplanation),
        ]

        if resource_type_filter:
            models_to_process = [(name, model) for name, model in models_to_process if name == resource_type_filter]

        total_created = 0

        for rtype, model_cls in models_to_process:
            qs = model_cls.objects.all()
            if grade_id and hasattr(model_cls, "grade_id"):
                qs = qs.filter(grade_id=grade_id)
            if subject_id and hasattr(model_cls, "subject_id"):
                qs = qs.filter(subject_id=subject_id)

            count = qs.count()
            self.stdout.write(f"Processing {rtype} ({count} items)...")

            for item in qs.iterator(chunk_size=batch_size):
                item_id = str(item.pk)

                exists = SyncChange.objects.filter(resource_type=rtype, resource_id=item_id).exists()
                if not exists:
                    title = getattr(item, "title", str(item))
                    metadata = {
                        "title": title[:200] if title else "",
                        "updated_at": item.updated_at.isoformat() if hasattr(item, "updated_at") and item.updated_at else timezone.now().isoformat(),
                    }

                    if hasattr(item, "file_path") and item.file_path:
                        try:
                            file_path = item.file_path.path
                            with open(file_path, "rb") as f:
                                file_bytes = f.read()
                                metadata["checksum_sha256"] = hashlib.sha256(file_bytes).hexdigest()
                                metadata["size_bytes"] = len(file_bytes)
                        except Exception:
                            pass

                    if not dry_run:
                        SyncChange.objects.create(
                            resource_type=rtype,
                            resource_id=item_id,
                            action=SyncChangeAction.UPSERT,
                            resource_version="1",
                            metadata_snapshot=metadata,
                            changed_at=timezone.now(),
                        )
                    total_created += 1

        self.stdout.write(self.style.SUCCESS(f"Rebuild completed! Total SyncChange records created: {total_created}"))
