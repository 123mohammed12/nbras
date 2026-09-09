"""Idempotent AR-05 review Mock blueprint provisioning."""

from decimal import Decimal

from django.db import transaction

from apps.assessments.models import AssessmentBlueprint, AssessmentBlueprintVersion
from apps.attempts.services.mock_exams import (
    blueprint_pool_readiness,
    publish_blueprint_version,
)
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Subject


DATASET_KEY = "ar05_mock_review_v1"
SUBJECT_ID = "3s_sci_quran"
TITLE = "محاكاة شاملة"
UNIT_DISTRIBUTION = {
    "3s_sci_quran_fy_u1": 12,
    "3s_sci_quran_fy_u2": 6,
    "3s_sci_quran_fy_u3": 6,
}
DIFFICULTY_DISTRIBUTION = {"easy": 8, "medium": 15, "hard": 1}
QUESTION_TYPE_DISTRIBUTION = {"multiple_choice": 16, "true_false": 8}
SELECTION_BUCKETS = [
    {"source": "training", "unit_id": "3s_sci_quran_fy_u1", "difficulty": "easy", "question_type": "multiple_choice", "count": 4},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u1", "difficulty": "medium", "question_type": "multiple_choice", "count": 4},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u1", "difficulty": "medium", "question_type": "true_false", "count": 3},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u1", "difficulty": "hard", "question_type": "true_false", "count": 1},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u2", "difficulty": "easy", "question_type": "multiple_choice", "count": 2},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u2", "difficulty": "medium", "question_type": "multiple_choice", "count": 2},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u2", "difficulty": "medium", "question_type": "true_false", "count": 2},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u3", "difficulty": "easy", "question_type": "multiple_choice", "count": 2},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u3", "difficulty": "medium", "question_type": "multiple_choice", "count": 2},
    {"source": "training", "unit_id": "3s_sci_quran_fy_u3", "difficulty": "medium", "question_type": "true_false", "count": 2},
]


def _version(blueprint):
    return AssessmentBlueprintVersion(
        blueprint=blueprint,
        version_number=1,
        title=TITLE,
        status=ContentStatus.DRAFT,
        question_count=24,
        duration_minutes=40,
        total_points=Decimal("24.00"),
        source_types=["training"],
        years=[],
        scope={"mode": "subject", "unit_ids": [], "lesson_ids": []},
        unit_distribution=UNIT_DISTRIBUTION,
        difficulty_distribution=DIFFICULTY_DISTRIBUTION,
        question_type_distribution=QUESTION_TYPE_DISTRIBUTION,
        selection_buckets=SELECTION_BUCKETS,
        selection_policy_version=2,
    )


class MockReviewImporter:
    def __init__(self, subject_id=SUBJECT_ID):
        self.subject = Subject.objects.get(id=subject_id)

    def preview(self):
        blueprint = AssessmentBlueprint(
            key=DATASET_KEY, title=TITLE, subject=self.subject,
        )
        readiness = blueprint_pool_readiness(_version(blueprint))
        return self._report(readiness, action="preview")

    @transaction.atomic
    def execute(self):
        blueprint, created = AssessmentBlueprint.objects.update_or_create(
            key=DATASET_KEY,
            defaults={
                "title": TITLE,
                "description": "اختبار تجريبي شامل وفق توزيع المنصة؛ ليس مخططاً وزارياً رسمياً.",
                "subject": self.subject,
                "assessment": None,
            },
        )
        values = _version(blueprint)
        version_defaults = {
            field: getattr(values, field)
            for field in (
                "title", "question_count", "duration_minutes", "total_points",
                "source_types", "years", "scope", "unit_distribution",
                "difficulty_distribution", "question_type_distribution",
                "selection_buckets", "selection_policy_version",
            )
        }
        version, version_created = AssessmentBlueprintVersion.objects.get_or_create(
            blueprint=blueprint,
            version_number=1,
            defaults=version_defaults,
        )
        if not version_created and any(
            getattr(version, field) != value for field, value in version_defaults.items()
        ):
            raise ApplicationError(
                "Published review policy v1 is immutable; create a new version.",
                code="STALE_BLUEPRINT_VERSION",
            )
        readiness = publish_blueprint_version(version)
        report = self._report(readiness, action="execute")
        report.update({"blueprint_created": created, "version_created": version_created})
        return report

    @transaction.atomic
    def remove(self):
        blueprint = AssessmentBlueprint.objects.filter(key=DATASET_KEY).first()
        if blueprint is None:
            return {"dataset": DATASET_KEY, "action": "remove", "removed": False, "reason": "not_found"}
        if blueprint.assessmentattempt_set.exists():
            return {"dataset": DATASET_KEY, "action": "remove", "removed": False, "reason": "historical_attempts_exist"}
        blueprint.delete()
        return {"dataset": DATASET_KEY, "action": "remove", "removed": True}

    def _report(self, readiness, *, action):
        return {
            "dataset": DATASET_KEY,
            "action": action,
            "subject_id": str(self.subject.id),
            "title": TITLE,
            "question_count": 24,
            "duration_minutes": 40,
            "total_points": 24,
            "source_policy": ["training"],
            "unit_distribution": UNIT_DISTRIBUTION,
            "difficulty_distribution": DIFFICULTY_DISTRIBUTION,
            "question_type_distribution": QUESTION_TYPE_DISTRIBUTION,
            "readiness": readiness,
        }
