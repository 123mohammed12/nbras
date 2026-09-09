from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from apps.analytics.models import AnalyticsEvent


class Command(BaseCommand):
    help = "Purges old analytics events based on retention policy."

    def add_arguments(self, parser):
        parser.add_argument("--before", type=str, help="YYYY-MM-DD cutoff date")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        is_dry = options["dry_run"]
        
        if options["before"]:
            from datetime import datetime
            cutoff = datetime.strptime(options["before"], "%Y-%m-%d").astimezone(timezone.get_current_timezone())
        else:
            days = getattr(settings, "ANALYTICS_EVENT_RETENTION_DAYS", 365)
            cutoff = timezone.now() - timedelta(days=days)
            
        qs = AnalyticsEvent.objects.filter(occurred_at__lt=cutoff)
        count = qs.count()
        
        if is_dry:
            self.stdout.write(f"DRY RUN: Would delete {count} AnalyticsEvent records older than {cutoff}.")
        else:
            deleted, _ = qs.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} AnalyticsEvent records older than {cutoff}."))
