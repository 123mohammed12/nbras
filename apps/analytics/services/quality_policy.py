from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings


@dataclass(frozen=True)
class QuestionQualityPolicy:
    version: str = "ar09-v1"
    minimum_sample_size: int = 30
    very_high_correct_rate: Decimal = Decimal("0.95")
    very_low_correct_rate: Decimal = Decimal("0.20")
    high_skip_rate: Decimal = Decimal("0.30")
    ineffective_distractor_rate: Decimal = Decimal("0.02")
    answer_key_issue_wrong_option_rate: Decimal = Decimal("0.60")


def get_question_quality_policy() -> QuestionQualityPolicy:
    return QuestionQualityPolicy(
        version=str(getattr(settings, "QUESTION_QUALITY_POLICY_VERSION", "ar09-v1")),
        minimum_sample_size=int(
            getattr(settings, "QUESTION_QUALITY_MIN_SAMPLE_SIZE", 30)
        ),
        very_high_correct_rate=Decimal(
            str(getattr(settings, "QUESTION_QUALITY_VERY_HIGH_CORRECT_RATE", "0.95"))
        ),
        very_low_correct_rate=Decimal(
            str(getattr(settings, "QUESTION_QUALITY_VERY_LOW_CORRECT_RATE", "0.20"))
        ),
        high_skip_rate=Decimal(
            str(getattr(settings, "QUESTION_QUALITY_HIGH_SKIP_RATE", "0.30"))
        ),
        ineffective_distractor_rate=Decimal(
            str(getattr(settings, "QUESTION_QUALITY_INEFFECTIVE_DISTRACTOR_RATE", "0.02"))
        ),
        answer_key_issue_wrong_option_rate=Decimal(
            str(getattr(settings, "QUESTION_QUALITY_ANSWER_KEY_ISSUE_RATE", "0.60"))
        ),
    )
