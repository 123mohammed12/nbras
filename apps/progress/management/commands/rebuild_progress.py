import logging
from django.core.management.base import BaseCommand
from apps.curriculum.models import StudyEnrollment
from apps.progress.models import SubjectProgress, UnitProgress, LessonProgress
from apps.progress.services.recalculation import recalculate_subject_progress

logger = logging.getLogger("progress.commands")


class Command(BaseCommand):
    help = "Rebuilds progress statistics from attempts and resources."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, help="User ID")
        parser.add_argument("--enrollment", type=str, help="Enrollment ID")
        parser.add_argument("--subject", type=str, help="Subject ID")
        parser.add_argument("--all", action="store_true", help="Rebuild all")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        is_dry = options["dry_run"]
        if is_dry:
            self.stdout.write("DRY RUN: No changes will be saved.")
            
        enrollments = StudyEnrollment.objects.filter(is_active=True)
        if options["user"]:
            enrollments = enrollments.filter(user_id=options["user"])
        if options["enrollment"]:
            enrollments = enrollments.filter(id=options["enrollment"])
            
        for en in enrollments:
            self.stdout.write(f"Processing enrollment {en.id} for user {en.user_id}")
            if not is_dry:
                # To fully rebuild, we just call recalculate_subject_progress for each subject the user has started
                subject_ids = SubjectProgress.objects.filter(user=en.user, study_enrollment=en).values_list("subject_id", flat=True)
                for sid in subject_ids:
                    recalculate_subject_progress(user=en.user, enrollment=en, subject_id=str(sid))
                    
        self.stdout.write(self.style.SUCCESS("Rebuild progress complete."))
