"""
Management command to clean up expired idempotency records.

Usage:
    python manage.py cleanup_idempotency_records [--batch-size 1000] [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.models import IdempotencyRecord


class Command(BaseCommand):
    help = "Removes expired IdempotencyRecord rows in batches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to delete per batch (default: 1000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate cleanup without actually deleting records.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        now = timezone.now()

        expired_qs = IdempotencyRecord.objects.filter(expires_at__lt=now)
        total_expired = expired_qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Found {total_expired} expired idempotency record(s) eligible for deletion."
                )
            )
            return

        self.stdout.write(
            f"Starting cleanup of {total_expired} expired idempotency record(s) (batch size: {batch_size})..."
        )

        total_deleted = 0
        while True:
            # Get next batch of IDs
            batch_ids = list(expired_qs.values_list("id", flat=True)[:batch_size])
            if not batch_ids:
                break

            deleted_count, _ = IdempotencyRecord.objects.filter(id__in=batch_ids).delete()
            total_deleted += deleted_count
            self.stdout.write(f"Deleted batch of {deleted_count} records...")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully deleted {total_deleted} expired idempotency record(s)."
            )
        )
