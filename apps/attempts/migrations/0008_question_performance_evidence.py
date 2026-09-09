import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


def backfill_performance_evidence(apps, schema_editor):
    AttemptAnswer = apps.get_model("attempts", "AttemptAnswer")
    Evidence = apps.get_model("attempts", "QuestionPerformanceEvidence")
    Event = apps.get_model("attempts", "QuestionPerformanceEvent")
    answers = AttemptAnswer.objects.filter(
        attempt__status__in=("submitted", "evaluated", "pending_review", "expired"),
        attempt_question__is_reference=False,
        is_correct__isnull=False,
    ).select_related(
        "attempt",
        "attempt_question__question_version__question",
        "attempt_question__ministerial_exam_item",
    ).order_by("attempt__submitted_at", "created_at")
    for answer in answers.iterator(chunk_size=500):
        if not (
            answer.selected_option_id
            or answer.selected_option_key
            or answer.answer_text
            or answer.answer_payload
        ):
            continue
        aq = answer.attempt_question
        question = aq.question_version.question
        if aq.source_type == "ministerial" and aq.ministerial_exam_item_id:
            identity = f"ministerial:{aq.ministerial_exam_item_id}"
        else:
            identity = f"{aq.source_type}:question:{question.id}"
        maximum = aq.points
        if answer.is_correct is True or (maximum and answer.awarded_points >= maximum):
            outcome = "correct"
        elif answer.awarded_points > 0:
            outcome = "partial"
        else:
            outcome = "incorrect"
        occurred_at = answer.attempt.evaluated_at or answer.attempt.submitted_at or answer.updated_at
        evidence, _ = Evidence.objects.get_or_create(
            user_id=answer.attempt.user_id,
            study_enrollment_id=answer.attempt.study_enrollment_id,
            identity_key=identity,
            defaults={
                "source_type": aq.source_type,
                "question_id": question.id,
                "question_version_id": aq.question_version_id,
                "ministerial_exam_item_id": aq.ministerial_exam_item_id,
                "subject_id": question.subject_id,
                "unit_id": question.unit_id,
                "lesson_id": question.lesson_id,
                "difficulty": question.difficulty,
                "question_type": question.question_type,
                "last_attempt_question_id": aq.id,
                "last_seen_at": occurred_at,
            },
        )
        had_wrong = evidence.wrong_count > 0
        if outcome in ("incorrect", "partial"):
            evidence.wrong_count += 1
            evidence.last_wrong_at = occurred_at
            evidence.last_wrong_attempt_question_id = aq.id
        else:
            evidence.correct_count += 1
            if had_wrong:
                evidence.correct_after_wrong_count += 1
        if answer.attempt.dynamic_assessment_type == "wrong_answers_test":
            evidence.last_practiced_at = occurred_at
        evidence.question_version_id = aq.question_version_id
        evidence.last_outcome = outcome
        evidence.last_awarded_points = answer.awarded_points
        evidence.last_maximum_points = maximum
        evidence.last_attempt_question_id = aq.id
        evidence.last_seen_at = occurred_at
        evidence.save()
        Event.objects.get_or_create(
            attempt_question_id=aq.id,
            defaults={
                "evidence_id": evidence.id,
                "outcome": outcome,
                "awarded_points": answer.awarded_points,
                "maximum_points": maximum,
                "occurred_at": occurred_at,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("attempts", "0007_backfill_direct_ministerial_occurrences"),
        ("curriculum", "0004_normalize_scoped_term_ids"),
        ("ministerial_exams", "0004_lesson_ministerial_batches"),
        ("question_bank", "0005_question_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuestionPerformanceEvidence",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("identity_key", models.CharField(max_length=100)),
                ("source_type", models.CharField(db_index=True, max_length=30)),
                ("difficulty", models.CharField(db_index=True, max_length=20)),
                ("question_type", models.CharField(db_index=True, max_length=30)),
                ("wrong_count", models.PositiveIntegerField(default=0)),
                ("correct_count", models.PositiveIntegerField(default=0)),
                ("correct_after_wrong_count", models.PositiveIntegerField(default=0)),
                ("last_outcome", models.CharField(blank=True, default="", max_length=20)),
                ("last_awarded_points", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("last_maximum_points", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("last_seen_at", models.DateTimeField()),
                ("last_wrong_at", models.DateTimeField(blank=True, null=True)),
                ("last_practiced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_attempt_question", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="latest_performance_evidence", to="attempts.attemptquestion")),
                ("last_wrong_attempt_question", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="latest_wrong_evidence", to="attempts.attemptquestion")),
                ("lesson", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="question_performance_evidence", to="curriculum.lesson")),
                ("ministerial_exam_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="performance_evidence", to="ministerial_exams.ministerialexamitem")),
                ("question", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="performance_evidence", to="question_bank.question")),
                ("question_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="performance_evidence", to="question_bank.questionversion")),
                ("study_enrollment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="question_performance_evidence", to="curriculum.studyenrollment")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="question_performance_evidence", to="curriculum.subject")),
                ("unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="question_performance_evidence", to="curriculum.unit")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="question_performance_evidence", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "attempt_question_performance_evidence"},
        ),
        migrations.CreateModel(
            name="QuestionPerformanceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("outcome", models.CharField(max_length=20)),
                ("awarded_points", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("maximum_points", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("occurred_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("attempt_question", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="performance_event", to="attempts.attemptquestion")),
                ("evidence", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="attempts.questionperformanceevidence")),
            ],
            options={"db_table": "attempt_question_performance_events"},
        ),
        migrations.AddConstraint(
            model_name="questionperformanceevidence",
            constraint=models.UniqueConstraint(fields=("user", "study_enrollment", "identity_key"), name="unique_question_performance_identity"),
        ),
        migrations.AddIndex(
            model_name="questionperformanceevidence",
            index=models.Index(fields=["user", "study_enrollment", "subject", "wrong_count"], name="att_ev_wrong_scope_idx"),
        ),
        migrations.AddIndex(
            model_name="questionperformanceevidence",
            index=models.Index(fields=["user", "study_enrollment", "lesson", "difficulty"], name="att_ev_weak_scope_idx"),
        ),
        migrations.RunPython(backfill_performance_evidence, migrations.RunPython.noop),
    ]
