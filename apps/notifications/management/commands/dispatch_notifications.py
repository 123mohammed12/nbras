from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.notifications.models import Notification
from apps.notifications.services import materialize_batch
from apps.notifications.delivery import dispatch_push


class Command(BaseCommand):
    help = "Publish due campaigns and dispatch a bounded FCM outbox batch."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--campaign-limit", type=int, default=10)
        parser.add_argument("--inbox-only", action="store_true")

    def handle(self, *args, **options):
        batch = max(1, min(options["batch_size"], 500))
        now = timezone.now()
        Notification.objects.filter(status__in=["PUBLISHED", "PUBLISHING", "SCHEDULED"], expires_at__lte=now).update(status="EXPIRED")
        due = list(Notification.objects.filter(status__in=["SCHEDULED", "PUBLISHING"], publish_at__lte=now).order_by("publish_at").values_list("pk", flat=True)[:max(1, min(options["campaign_limit"], 100))])
        count = sum(materialize_batch(pk, batch) for pk in due)
        sent = 0 if options["inbox_only"] else dispatch_push(batch)
        self.stdout.write(f"Recipients prepared: {count}; pushes sent: {sent}")
