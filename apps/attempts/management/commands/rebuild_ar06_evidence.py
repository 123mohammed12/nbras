from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.attempts.services.ar06_practice import rebuild_question_performance_evidence
from apps.curriculum.models import StudyEnrollment


class Command(BaseCommand):
    help = "Rebuild AR-06 exact-question evidence and AR-08 mastery from finalized attempts."

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
        count = rebuild_question_performance_evidence(
            user=user, enrollment=enrollment,
        )
        self.stdout.write(self.style.SUCCESS(f"Projected {count} graded question events and rebuilt mastery."))
