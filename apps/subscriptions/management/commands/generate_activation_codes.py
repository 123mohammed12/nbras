from django.core.management.base import BaseCommand, CommandError

from apps.common.exceptions import ApplicationError
from apps.subscriptions.models import SubscriptionPlan
from apps.subscriptions.services.batch_service import generate_activation_code_batch


class Command(BaseCommand):
    help = "Generates a batch of secure activation codes for a subscription plan using HMAC-SHA256."

    def add_arguments(self, parser):
        parser.add_argument("--plan", type=str, required=True, help="Plan code or UUID")
        parser.add_argument("--count", type=int, default=10, help="Number of codes to generate (max 5000)")
        parser.add_argument("--batch-code", type=str, default="", help="Batch code label")
        parser.add_argument("--output", type=str, default="", help="Output text file path for raw codes")

    def handle(self, *args, **options):
        plan_identifier = options["plan"]
        count = options["count"]
        batch_code = options["batch_code"]
        output_file = options["output"]

        if count < 1 or count > 5000:
            raise CommandError("Count must be between 1 and 5000.")

        plan = SubscriptionPlan.objects.filter(code=plan_identifier).first()
        if not plan:
            plan = SubscriptionPlan.objects.filter(id=plan_identifier).first()

        if not plan:
            raise CommandError(f"SubscriptionPlan '{plan_identifier}' not found.")

        if not plan.is_active:
            raise CommandError(f"SubscriptionPlan '{plan.name}' is inactive.")

        try:
            _batch, raw_codes = generate_activation_code_batch(
                plan=plan,
                quantity=count,
                batch_code=batch_code,
            )
        except ApplicationError as exc:
            raise CommandError(exc.message) from exc

        self.stdout.write(self.style.SUCCESS(f"Successfully generated {count} codes for plan '{plan.name}'."))

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                for r in raw_codes:
                    f.write(f"{r}\n")
            self.stdout.write(self.style.WARNING(f"WARNING: Raw codes saved to '{output_file}'. Keep this file secure!"))
        else:
            self.stdout.write(self.style.WARNING("=== RAW CODES (SHOWN ONCE ONLY) ==="))
            for r in raw_codes:
                self.stdout.write(r)
