from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.analytics.services.question_quality import rebuild_question_quality
from apps.curriculum.models import StudyEnrollment


class Command(BaseCommand):
    help = "Rebuild AR-09 question-quality contributions and aggregates."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int)
        parser.add_argument("--enrollment")

    def handle(self, *args, **options):
        user = None
        enrollment = None
        if options["user"] is not None:
            user = User.objects.filter(pk=options["user"]).first()
            if user is None:
                raise CommandError("User not found.")
        if options["enrollment"]:
            enrollment = StudyEnrollment.objects.filter(
                pk=options["enrollment"]
            ).first()
            if enrollment is None:
                raise CommandError("Enrollment not found.")
            if user is not None and enrollment.user_id != user.id:
                raise CommandError("Enrollment does not belong to the selected user.")
        changed = rebuild_question_quality(user=user, enrollment=enrollment)
        self.stdout.write(
            self.style.SUCCESS(
                f"Question quality rebuilt from {changed} finalized contributions."
            )
        )
