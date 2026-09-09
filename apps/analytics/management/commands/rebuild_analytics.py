import logging
from django.core.management.base import BaseCommand
from apps.curriculum.models import StudyEnrollment
from apps.analytics.services.insights_service import recalculate_student_insights

logger = logging.getLogger("analytics.commands")


class Command(BaseCommand):
    help = "Rebuilds analytics insights and summaries."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, help="User ID")
        parser.add_argument("--all", action="store_true", help="Rebuild all")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        is_dry = options["dry_run"]
        if is_dry:
            self.stdout.write("DRY RUN: No changes will be saved.")
            
        enrollments = StudyEnrollment.objects.filter(is_active=True)
        if options["user"]:
            enrollments = enrollments.filter(user_id=options["user"])
            
        for en in enrollments:
            self.stdout.write(f"Processing analytics for enrollment {en.id} user {en.user_id}")
            if not is_dry:
                recalculate_student_insights(user=en.user, enrollment=en)
                
        self.stdout.write(self.style.SUCCESS("Rebuild analytics complete."))
