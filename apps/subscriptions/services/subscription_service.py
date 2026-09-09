from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Subject
from apps.subscriptions.models import (
    PackageTierType, Subscription, SubscriptionAudit, SubscriptionPlan,
    SubscriptionSource, SubscriptionStatus,
)


def _plan_year(plan, enrollment):
    return plan.academic_year or enrollment.academic_year


def _eligible_subjects(enrollment):
    return Subject.objects.filter(
        grade_id=enrollment.grade_id,
        section_id=enrollment.section_id,
        status=ContentStatus.PUBLISHED,
    ).order_by("sort_order", "id")


def _validate_plan_context(plan, enrollment):
    if plan.grade_id and plan.grade_id != enrollment.grade_id:
        raise ApplicationError("الخطة لا تطابق الصف الدراسي الحالي.", code="ACADEMIC_CONTEXT_MISMATCH")
    if plan.section_id and plan.section_id != enrollment.section_id:
        raise ApplicationError("الخطة لا تطابق المسار الدراسي الحالي.", code="ACADEMIC_CONTEXT_MISMATCH")
    if plan.academic_year_id and plan.academic_year_id != enrollment.academic_year_id:
        raise ApplicationError("الخطة لا تطابق العام الدراسي الحالي.", code="ACADEMIC_CONTEXT_MISMATCH")
    entitlements = list(plan.plan_entitlements.filter(entitlement__is_active=True).select_related("entitlement"))
    if not entitlements:
        raise ApplicationError("الخطة لا تملك استحقاقاً صالحاً.", code="PLAN_HAS_NO_ENTITLEMENTS")
    def matches_academic_context(item):
        ent = item.entitlement
        if ent.grade_id and ent.grade_id != enrollment.grade_id:
            return False
        if ent.section_id and ent.section_id != enrollment.section_id:
            return False
        subject = ent.subject or (ent.unit.subject if ent.unit_id else None)
        if subject and (subject.grade_id != enrollment.grade_id or subject.section_id != enrollment.section_id):
            return False
        return True
    if not any(matches_academic_context(item) for item in entitlements):
        raise ApplicationError("الخطة لا تطابق السياق الدراسي الحالي.", code="ACADEMIC_CONTEXT_MISMATCH")


def _current_subscription(user, enrollment, year, lock=False):
    query = Subscription.objects.filter(
        user=user,
        study_enrollment=enrollment,
        academic_year=year,
        status=SubscriptionStatus.ACTIVE,
    ).prefetch_related("selected_subjects")
    if lock:
        query = query.select_for_update()
    return query.order_by("created_at").first()


def preview_subscription_grant(*, user, enrollment, plan, selected_subject_ids=None, allow_incomplete=False):
    if not plan.is_active:
        raise ApplicationError("الخطة غير نشطة.", code="PLAN_INACTIVE")
    _validate_plan_context(plan, enrollment)
    year = _plan_year(plan, enrollment)
    if plan.academic_year_id and year is None:
        raise ApplicationError("لا يوجد عام دراسي صالح للخطة.", code="ACADEMIC_CONTEXT_MISMATCH")
    eligible = list(_eligible_subjects(enrollment))
    eligible_by_id = {str(subject.id): subject for subject in eligible}
    requested = list(dict.fromkeys(str(value) for value in (selected_subject_ids or [])))
    invalid = [value for value in requested if value not in eligible_by_id]
    if invalid:
        raise ApplicationError("اختيار المواد غير صالح للسياق الدراسي.", code="INVALID_SUBJECT_SELECTION")

    current = _current_subscription(user, enrollment, year)
    owned = {str(subject.id) for subject in current.selected_subjects.all()} if current else set()
    already_all = bool(current and current.is_all_subjects)
    if already_all:
        raise ApplicationError("الاشتراك الحالي يشمل جميع المواد بالفعل.", code="NO_NET_NEW_ACCESS")
    if (
        current
        and plan.tier_type == PackageTierType.SUBJECT_COUNT
        and plan.subject_limit
        and len(owned) >= plan.subject_limit
    ):
        raise ApplicationError("الرمز لا يضيف وصولاً جديداً قابلاً للاستخدام.", code="NO_NET_NEW_ACCESS")

    if plan.tier_type == PackageTierType.ALL_SUBJECTS:
        resulting = set(eligible_by_id)
        new_subjects = resulting - owned
        is_all = True
    else:
        if not plan.subject_limit:
            # Legacy exact-entitlement plans need no user selection.
            resulting = owned | set(requested)
            new_subjects = set(requested) - owned
            is_all = False
        else:
            resulting = owned | set(requested)
            if len(resulting) != plan.subject_limit and not allow_incomplete:
                raise ApplicationError(
                    "يجب أن يطابق مجموع المواد المؤكدة حد الباقة.",
                    code="SUBJECT_SELECTION_COUNT_MISMATCH",
                )
            new_subjects = resulting - owned
            is_all = False
    if current and not new_subjects and not is_all and not allow_incomplete:
        raise ApplicationError("الرمز لا يضيف وصولاً جديداً قابلاً للاستخدام.", code="NO_NET_NEW_ACCESS")
    if not current and plan.subject_limit and not resulting and not allow_incomplete:
        raise ApplicationError("اختر المواد المطلوبة للباقة.", code="SUBJECT_SELECTION_REQUIRED")

    return {
        "academic_year": ({"code": year.code, "name": year.name_ar, "ends_at": year.ends_at.isoformat()} if year else None),
        "plan": {
            "id": str(plan.id), "name": plan.name,
            "tier_type": plan.tier_type, "subject_limit": plan.subject_limit,
        },
        "current_subject_ids": sorted(owned),
        "new_subject_ids": sorted(new_subjects),
        "resulting_subject_ids": sorted(resulting),
        "resulting_is_all_subjects": is_all,
        "eligible_subjects": [{"id": str(item.id), "name": item.name_ar} for item in eligible],
        "has_net_new_access": bool(new_subjects or is_all),
        "required_new_subject_count": (
            max(0, (plan.subject_limit or 0) - len(owned))
            if plan.tier_type == PackageTierType.SUBJECT_COUNT else 0
        ),
    }


@transaction.atomic
def grant_subscription_access(
    *, user, enrollment, plan: SubscriptionPlan, selected_subject_ids=None,
    source=SubscriptionSource.CODE, actor=None, reason="", usage=None,
):
    # Serialize all grants/generations for this academic actor/context.
    enrollment = type(enrollment).objects.select_for_update().get(pk=enrollment.pk)
    preview = preview_subscription_grant(
        user=user, enrollment=enrollment, plan=plan,
        selected_subject_ids=selected_subject_ids,
    )
    year = _plan_year(plan, enrollment)
    now = timezone.now()
    existing = _current_subscription(user, enrollment, year, lock=True)
    before = {
        "plan_id": str(existing.plan_id),
        "subject_ids": sorted(str(item.id) for item in existing.selected_subjects.all()),
        "is_all_subjects": existing.is_all_subjects,
    } if existing else {}
    expires_at = year.ends_at if year else now + timedelta(days=plan.duration_days)
    if expires_at <= now:
        raise ApplicationError("العام الدراسي المرتبط بالخطة منتهٍ.", code="ACADEMIC_YEAR_EXPIRED")

    source = SubscriptionSource.CODE if source == "activation_code" else source
    if existing:
        existing.plan = plan
        existing.is_all_subjects = preview["resulting_is_all_subjects"]
        existing.expires_at = expires_at
        existing.source = source
        existing.activated_at = now
        existing.activated_by = actor
        existing.activation_code_usage = usage or existing.activation_code_usage
        existing.commercial_snapshot = {
            "plan_id": str(plan.id), "plan_name": plan.name,
            "regular_price": str(plan.price),
            "display_price": str(plan.current_display_price(now)),
            "currency": plan.currency,
        }
        existing.save()
        subscription = existing
    else:
        subscription = Subscription.objects.create(
            user=user, study_enrollment=enrollment, academic_year=year,
            plan=plan, status=SubscriptionStatus.ACTIVE,
            starts_at=now, expires_at=expires_at,
            is_all_subjects=preview["resulting_is_all_subjects"], source=source,
            activated_at=now, activated_by=actor, activation_code_usage=usage,
            commercial_snapshot={
                "plan_id": str(plan.id), "plan_name": plan.name,
                "regular_price": str(plan.price),
                "display_price": str(plan.current_display_price(now)),
                "currency": plan.currency,
            },
        )
    if not subscription.is_all_subjects:
        # Additive only: never remove/replace previously confirmed subjects.
        subscription.selected_subjects.add(*preview["resulting_subject_ids"])
    after = {
        "plan_id": str(subscription.plan_id),
        "subject_ids": preview["resulting_subject_ids"],
        "is_all_subjects": subscription.is_all_subjects,
        "expires_at": subscription.expires_at.isoformat(),
    }
    SubscriptionAudit.objects.create(
        subscription=subscription,
        action="upgrade" if before else "activate",
        source=source, actor=actor, reason=reason,
        before_state=before, after_state=after,
    )
    from apps.notifications.services import subscription_event
    subscription_event(subscription, "activated")
    return subscription, preview


def activate_or_extend_subscription(*, user, enrollment, plan, source="activation_code", usage=None):
    subscription, _ = grant_subscription_access(
        user=user, enrollment=enrollment, plan=plan, source=source, usage=usage,
    )
    return subscription


def direct_activate_subscription(*, user, enrollment, plan, selected_subject_ids, actor, reason):
    if not actor or not (actor.is_staff or actor.is_superuser):
        raise ApplicationError("يتطلب التفعيل المباشر صلاحية إدارية.", code="ADMIN_PERMISSION_REQUIRED", status_code=403)
    if not reason.strip():
        raise ApplicationError("سبب التفعيل الإداري مطلوب.", code="AUDIT_REASON_REQUIRED")
    return grant_subscription_access(
        user=user, enrollment=enrollment, plan=plan,
        selected_subject_ids=selected_subject_ids,
        source=SubscriptionSource.ADMIN, actor=actor, reason=reason,
    )


@transaction.atomic
def cancel_subscription(subscription):
    subscription.status = SubscriptionStatus.CANCELLED
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


@transaction.atomic
def revoke_subscription(subscription):
    subscription.status = SubscriptionStatus.REVOKED
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


def refresh_subscription_status(subscription):
    if subscription.status == SubscriptionStatus.ACTIVE and subscription.expires_at <= timezone.now():
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.save(update_fields=["status", "updated_at"])
        from apps.notifications.services import subscription_event
        subscription_event(subscription, "expired")
    return subscription
