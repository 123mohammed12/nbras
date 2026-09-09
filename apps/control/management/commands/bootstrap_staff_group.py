"""
Management command to provision or synchronize the Staff group and baseline permissions.
"""

from django.core.management.base import BaseCommand
from apps.control.services.bootstrap import ensure_staff_group


class Command(BaseCommand):
    help = "Idempotently provision the Staff group with baseline operational permissions."

    def handle(self, *args, **options):
        self.stdout.write("Bootstrapping Operations Console Staff group...")
        result = ensure_staff_group()
        if result["created"]:
            self.stdout.write(self.style.SUCCESS("Created new 'Staff' group."))
        else:
            self.stdout.write(self.style.SUCCESS("Found existing 'Staff' group."))

        self.stdout.write(
            self.style.SUCCESS(
                f"Assigned {result['assigned_count']} baseline permissions to 'Staff'."
            )
        )
        if result["missing"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: {len(result['missing'])} permissions were missing: {', '.join(result['missing'])}"
                )
            )
