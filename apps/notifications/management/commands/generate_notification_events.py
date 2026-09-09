from django.core.management.base import BaseCommand
from apps.notifications.services import generate_subscription_events


class Command(BaseCommand):
    help = "Generate idempotent subscription expiry/expiration Inbox events."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        count = generate_subscription_events(max(1, min(options["batch_size"], 1000)))
        self.stdout.write(f"Events generated: {count}")
