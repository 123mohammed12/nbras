"""Central, deterministic AR-08 mastery policy.

Policy ar08-v1:
- one independent contribution per exact AR-06 identity;
- the latest non-remediation result is the baseline;
- a later Wrong/Weakness remediation result can move that baseline by 25%;
- a genuinely new identity first seen in Weakness Practice contributes normally;
- recency weights are bucketed and never delete historical evidence;
- trend compares two multi-question windows and needs three identities per window.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings


@dataclass(frozen=True)
class MasteryPolicy:
    version: str = "ar08-v1"
    remediation_share: Decimal = Decimal("0.25")
    recent_days: int = 30
    prior_days: int = 90
    older_days: int = 180
    recent_weight: Decimal = Decimal("1.00")
    prior_weight: Decimal = Decimal("0.75")
    older_weight: Decimal = Decimal("0.50")
    historical_weight: Decimal = Decimal("0.25")
    breakdown_min_distinct: int = 3
    weakness_min_distinct: int = 5
    weakness_min_effective: Decimal = Decimal("3.00")
    weakness_max_score: Decimal = Decimal("0.60")
    high_priority_max_score: Decimal = Decimal("0.40")
    moderate_confidence_min: int = 5
    strong_confidence_min: int = 15
    trend_min_distinct: int = 3
    trend_delta: Decimal = Decimal("0.10")


def get_mastery_policy() -> MasteryPolicy:
    """One configurable/versioned policy seam; callers never embed thresholds."""

    return MasteryPolicy(
        version=str(getattr(settings, "MASTERY_POLICY_VERSION", "ar08-v1")),
        remediation_share=Decimal(str(getattr(settings, "MASTERY_REMEDIATION_SHARE", "0.25"))),
        weakness_min_distinct=int(getattr(settings, "MASTERY_WEAKNESS_MIN_DISTINCT", 5)),
        weakness_min_effective=Decimal(str(getattr(settings, "MASTERY_WEAKNESS_MIN_EFFECTIVE", "3.00"))),
        weakness_max_score=Decimal(str(getattr(settings, "MASTERY_WEAKNESS_MAX_SCORE", "0.60"))),
    )
