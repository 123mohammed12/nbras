from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.curriculum.models import StudyEnrollment
from apps.progress.services.mastery import rebuild_mastery_read_models


class Command(BaseCommand):
    help = "Rebuild AR-08 mastery read models from projected exact-question evidence."

    def add_arguments(self, parser):
        parser.add_argument("--user-id")
        parser.add_argument("--enrollment-id")

    def handle(self, *args, **options):
        user = None
        enrollment = None
        if options["user_id"]:
            user = User.objects.filter(id=options["user_id"]).first()
            if user is None:
                raise CommandError("User was not found.")
        if options["enrollment_id"]:
            enrollment = StudyEnrollment.objects.filter(id=options["enrollment_id"]).first()
            if enrollment is None:
                raise CommandError("Enrollment was not found.")
            if user is not None and enrollment.user_id != user.id:
                raise CommandError("Enrollment does not belong to the selected user.")
        count = rebuild_mastery_read_models(user=user, enrollment=enrollment)
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {count} mastery scope aggregates."))
