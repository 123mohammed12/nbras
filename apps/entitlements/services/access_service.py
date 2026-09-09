import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone

from apps.curriculum.models import ContentStatus, StudyEnrollment, Subject, Unit
from apps.entitlements.models import FreeAccessPolicy, UserEntitlement
from apps.entitlements.registry import ResourceAccessRegistry
from apps.entitlements.services.entitlement_matching import entitlement_matches_resource
from apps.subscriptions.models import Subscription, SubscriptionStatus

logger = logging.getLogger("entitlements.access_service")


@dataclass
class AccessDecision:
    allowed: bool
    reason_code: str
    source: str = "system"
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    requires_subscription: bool = False
    upgrade_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_status": (
                "FREE" if self.allowed and self.source.startswith("free") else
                "ENTITLED" if self.allowed else
                "TEMPORARILY_UNAVAILABLE" if self.reason_code == "ENTITLEMENT_SERVICE_UNAVAILABLE" else
                "EXPIRED" if self.reason_code == "SUBSCRIPTION_EXPIRED" else
                "NOT_APPLICABLE" if self.reason_code in {"ACADEMIC_CONTEXT_MISMATCH", "RESOURCE_UNPUBLISHED", "NO_ENROLLMENT"} else
                "LOCKED"
            ),
            "is_locked": not self.allowed,
            "lock_reason": None if self.allowed else self.reason_code,
            "access": self.allowed,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "source": self.source,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "requires_subscription": self.requires_subscription,
            "upgrade_required": self.upgrade_required,
        }


def _ensure_free_policies(enrollment):
    """Persist the first eligible unit once for every published subject."""
    year_id = enrollment.academic_year_id
    existing = FreeAccessPolicy.objects.filter(
        academic_year_id=year_id, grade_id=enrollment.grade_id,
        section_id=enrollment.section_id, subject_id=OuterRef('pk'),
    )
    first_unit = Unit.objects.filter(
        subject_id=OuterRef('pk'), status=ContentStatus.PUBLISHED,
    ).order_by('sort_order', 'id').values('pk')[:1]
    missing = Subject.objects.filter(
        grade_id=enrollment.grade_id,
        section_id=enrollment.section_id,
        status=ContentStatus.PUBLISHED,
    ).annotate(has_policy=Exists(existing), selected_unit=Subquery(first_unit)).filter(has_policy=False)
    rows = list(missing.values('pk', 'selected_unit'))
    if not rows:
        return
    with transaction.atomic():
        # Serialize initialization for the same subjects, including legacy NULL years.
        list(Subject.objects.select_for_update().filter(pk__in=[r['pk'] for r in rows]).order_by('pk').values_list('pk', flat=True))
        # Re-evaluate after the lock, since another request may have initialized them.
        rows = list(missing.values('pk', 'selected_unit'))
        # Hierarchy and publication are validated by the scoped query above.
        FreeAccessPolicy.objects.bulk_create([
            FreeAccessPolicy(academic_year_id=year_id, grade_id=enrollment.grade_id,
                section_id=enrollment.section_id, subject_id=row['pk'], free_unit_id=row['selected_unit'])
            for row in rows
        ], ignore_conflicts=True)


@dataclass
class AccessContext:
    user: Any
    enrollment: Optional[StudyEnrollment]
    now: datetime
    is_staff: bool
    free_access_policies: List[FreeAccessPolicy]
    user_entitlements: List[UserEntitlement]
    active_subscriptions: List[Subscription]
    has_expired_subscription: bool = False
    expired_user_entitlements: List[UserEntitlement] = field(default_factory=list)

    @classmethod
    def build(cls, user, enrollment=None):
        now = timezone.now()
        if not user or not getattr(user, "is_authenticated", False):
            return cls(user, None, now, False, [], [], [])
        is_staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
        if not enrollment:
            enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).select_related("grade", "section", "academic_year").first()
        if not is_staff and enrollment and (str(enrollment.user_id) != str(user.pk) or not enrollment.is_active):
            return cls(user, None, now, False, [], [], [])
        if not enrollment or is_staff:
            return cls(user, enrollment, now, is_staff, [], [], [])

        _ensure_free_policies(enrollment)
        policies = list(FreeAccessPolicy.objects.filter(
            grade_id=enrollment.grade_id,
            section_id=enrollment.section_id,
            academic_year_id=enrollment.academic_year_id,
            is_active=True,
        ).select_related("free_unit", "subject"))
        all_grants = list(UserEntitlement.objects.filter(
            user=user, study_enrollment=enrollment, is_active=True,
            starts_at__lte=now, revoked_at__isnull=True,
        ).select_related("entitlement"))
        grants = [grant for grant in all_grants if grant.expires_at and grant.expires_at > now]
        expired_grants = [grant for grant in all_grants if grant.expires_at and grant.expires_at <= now]
        subscriptions = list(Subscription.objects.filter(
            user=user, study_enrollment=enrollment, status=SubscriptionStatus.ACTIVE,
            starts_at__lte=now, expires_at__gt=now,
        ).select_related("plan", "academic_year").prefetch_related(
            "selected_subjects", "plan__plan_entitlements__entitlement",
        ))
        expired = Subscription.objects.filter(
            user=user, study_enrollment=enrollment,
        ).filter(expires_at__lte=now).exists()
        return cls(user, enrollment, now, False, policies, grants, subscriptions, expired, expired_grants)

    def policy_for_subject(self, subject_id):
        return next((p for p in self.free_access_policies if str(p.subject_id) == str(subject_id)), None)


def _subscription_covers(sub, scope):
    subject_id = scope.get("subject_id")
    # FE-08 tier subscriptions keep the accepted PlanEntitlement chain as the
    # broad academic entitlement, then apply the subscription's fixed subject scope.
    matching_plan_entitlement = any(
        entitlement_matches_resource(item.entitlement, scope)
        for item in sub.plan.plan_entitlements.all()
    )
    if not matching_plan_entitlement:
        return False
    if not subject_id:
        return True
    if sub.is_all_subjects:
        return (
            str(scope.get("grade_id")) == str(sub.study_enrollment.grade_id)
            and str(scope.get("section_id")) == str(sub.study_enrollment.section_id)
        )
    selected = {str(item.id) for item in sub.selected_subjects.all()}
    # Legacy subscriptions without FE-08 selection retain their exact entitlement semantics.
    return not selected or str(subject_id) in selected


def evaluate_access_with_context(context, resource_type, resource_id, resource_data=None):
    if context.is_staff:
        return AccessDecision(True, "STAFF_ACCESS", "staff")
    if not context.user or not getattr(context.user, "is_authenticated", False):
        return AccessDecision(False, "AUTHENTICATION_REQUIRED", requires_subscription=True)
    if not context.enrollment:
        return AccessDecision(False, "NO_ENROLLMENT", requires_subscription=True)
    if not resource_data:
        resource_data = ResourceAccessRegistry.resolve_resource(resource_type, str(resource_id))
    if not resource_data or not resource_data.get("is_published"):
        return AccessDecision(False, "RESOURCE_UNPUBLISHED", scope_type=resource_type, scope_id=str(resource_id))
    scope = resource_data["scope"]
    if scope.get("grade_id") and str(scope["grade_id"]) != str(context.enrollment.grade_id):
        return AccessDecision(False, "ACADEMIC_CONTEXT_MISMATCH", scope_type="grade", scope_id=str(scope["grade_id"]), upgrade_required=True)
    if scope.get("section_id") and str(scope["section_id"]) != str(context.enrollment.section_id):
        return AccessDecision(False, "ACADEMIC_CONTEXT_MISMATCH", scope_type="section", scope_id=str(scope["section_id"]), upgrade_required=True)

    policy = context.policy_for_subject(scope.get("subject_id"))
    if policy:
        if resource_type == "summary" and not scope.get("unit_id") and policy.subject_summaries_free:
            return AccessDecision(True, "FREE_ACCESS", "free_subject_summary", "subject", str(scope.get("subject_id")))
        if resource_type in {"ministerial_exam", "assessment"} and resource_data.get("free_access_rank") and resource_data["free_access_rank"] <= policy.free_ministerial_count:
            return AccessDecision(True, "FREE_ACCESS", "free_ministerial", "subject", str(scope.get("subject_id")))
        if resource_type == "training_batch" and resource_data.get("free_access_rank") and resource_data["free_access_rank"] <= policy.free_subject_training_count:
            return AccessDecision(True, "FREE_ACCESS", "free_training", "subject", str(scope.get("subject_id")))
        if resource_data.get("applies_free_unit") and scope.get("unit_id") and str(policy.free_unit_id) == str(scope["unit_id"]):
            return AccessDecision(True, "FREE_UNIT_ACCESS", "free_unit", "unit", str(scope["unit_id"]))

    for grant in context.user_entitlements:
        if entitlement_matches_resource(grant.entitlement, scope):
            return AccessDecision(True, "EXPLICIT_USER_ENTITLEMENT", "user_entitlement", grant.entitlement.scope_type, str(grant.entitlement_id), grant.expires_at)
    for sub in context.active_subscriptions:
        if _subscription_covers(sub, scope):
            return AccessDecision(True, "SUBSCRIPTION_ACCESS", "subscription", "subject", str(scope.get("subject_id") or ""), sub.expires_at)

    has_active_other = bool(context.active_subscriptions)
    if any(entitlement_matches_resource(grant.entitlement, scope) for grant in context.expired_user_entitlements):
        reason = "SUBSCRIPTION_EXPIRED"
    elif has_active_other and scope.get("subject_id"):
        reason = "SUBJECT_NOT_INCLUDED"
    elif context.has_expired_subscription:
        reason = "SUBSCRIPTION_EXPIRED"
    else:
        reason = "SUBSCRIPTION_REQUIRED"
    return AccessDecision(False, reason, "subscription", resource_type, str(resource_id), requires_subscription=True, upgrade_required=True)


def check_resource_access(*, user, enrollment=None, resource_type, resource_id, context=None):
    try:
        context = context or AccessContext.build(user=user, enrollment=enrollment)
        return evaluate_access_with_context(context, resource_type, resource_id)
    except Exception as exc:
        logger.exception("Access evaluation failed user=%s type=%s id=%s", getattr(user, "id", None), resource_type, resource_id)
        return AccessDecision(False, "ENTITLEMENT_SERVICE_UNAVAILABLE", requires_subscription=True)


def check_resources_access_batch(*, user, enrollment=None, resources, context=None):
    results = {}
    resources = list(resources)
    try:
        context = context or AccessContext.build(user=user, enrollment=enrollment)
        resolved = ResourceAccessRegistry.resolve_resources_batch(resources)
    except Exception:
        logger.exception("Batch access evaluation unavailable")
        context, resolved = None, {}
    for item in resources:
        resource_type = item.get("resource_type") or item.get("type")
        resource_id = str(item.get("resource_id") or item.get("id"))
        if not resource_type or not resource_id:
            continue
        try:
            decision = (
                evaluate_access_with_context(context, resource_type, resource_id, resolved.get((resource_type, resource_id)))
                if context else AccessDecision(False, "ENTITLEMENT_SERVICE_UNAVAILABLE")
            )
        except Exception:
            logger.exception("Batch resource access unavailable")
            decision = AccessDecision(False, "ENTITLEMENT_SERVICE_UNAVAILABLE")
        results[f"{resource_type}:{resource_id}"] = decision
        results[(resource_type, resource_id)] = decision
    return results


def check_attempt_snapshot_access(*, user, attempt):
    """Existing policy: snapshots already acquired belong to their attempt owner.

    This does not authorize a retry, new questions, or the source assessment.
    The attempt service still enforces deadlines, status and answer revisions.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return AccessDecision(False, "AUTHENTICATION_REQUIRED")
    if attempt is None or str(attempt.user_id) != str(user.pk):
        return AccessDecision(False, "ATTEMPT_NOT_FOUND")
    return AccessDecision(True, "OWNED_ATTEMPT_SNAPSHOT", "attempt_snapshot")
