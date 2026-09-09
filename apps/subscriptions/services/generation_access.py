from dataclasses import dataclass

from apps.entitlements.services.access_service import AccessContext, check_resource_access
from apps.subscriptions.models import FreeGenerationUse, GenerationMode


@dataclass(frozen=True)
class GenerationAccess:
    allowed: bool
    reason_code: str
    is_free_generation: bool = False


def check_subject_generation_access(*, user, enrollment, subject, mode):
    paid = check_resource_access(
        user=user, enrollment=enrollment,
        resource_type="subject", resource_id=str(subject.id),
    )
    if paid.allowed:
        return GenerationAccess(True, "SUBSCRIPTION_ACCESS", False)
    # A free allowance cannot override missing identity, invalid scope or errors.
    if paid.reason_code not in {
        "SUBSCRIPTION_REQUIRED", "SUBSCRIPTION_EXPIRED", "SUBJECT_NOT_INCLUDED",
    }:
        return GenerationAccess(False, paid.reason_code)
    if mode not in {GenerationMode.MOCK, GenerationMode.CUSTOM}:
        return GenerationAccess(False, "INVALID_GENERATION_MODE")

    # Published Mock exams are a free learning feature.  Keep their usage
    # records for analytics/question rotation, but never turn the blueprint
    # into a subscription lock after the first attempt.
    if mode == GenerationMode.MOCK:
        return GenerationAccess(True, "FREE_ACCESS", True)

    context = AccessContext.build(user=user, enrollment=enrollment)
    policy = context.policy_for_subject(subject.id)
    if policy is None:
        return GenerationAccess(False, "SUBSCRIPTION_REQUIRED")
    allowance = policy.free_subject_custom_generations
    used = FreeGenerationUse.objects.filter(
        user=user,
        academic_year_id=enrollment.academic_year_id,
        subject=subject,
        mode=mode,
    ).count()
    if used < allowance:
        return GenerationAccess(True, "FREE_ACCESS", True)
    return GenerationAccess(
        False,
        "FREE_CUSTOM_ALREADY_USED",
    )
