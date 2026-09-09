"""Non-commercial access metadata for the consumption-only client."""
from django.utils import timezone

from apps.entitlements.models import UserEntitlement
from apps.entitlements.services.access_service import AccessContext
from apps.subscriptions.models import Subscription


def access_overview(user, enrollment):
    context = AccessContext.build(user, enrollment)
    policies = context.free_access_policies
    # Only promise benefits common to every policy in this enrollment.
    free = {
        "free_unit_count": int(bool(policies) and all(p.free_unit_id for p in policies)),
        "subject_summaries_free": bool(policies) and all(p.subject_summaries_free for p in policies),
        "mock_exams_free": enrollment is not None,
    }
    for field in ("free_ministerial_count", "free_subject_training_count",
                  "free_subject_custom_generations", "free_mock_generations"):
        free[field] = min((getattr(p, field) for p in policies), default=0)
    grants = [g for g in context.user_entitlements if g.entitlement.is_active]
    subscriptions = [s for s in context.active_subscriptions
                     if any(p.entitlement.is_active for p in s.plan.plan_entitlements.all())]
    expired = context.has_expired_subscription or bool(enrollment and UserEntitlement.objects.filter(
        user=user, study_enrollment=enrollment, expires_at__lte=context.now,
    ).exists())
    scopes = []
    for grant in grants:
        ent = grant.entitlement
        scopes.append({
            "name": ent.name, "scope_type": ent.scope_type,
            "scope_id": str(getattr(ent, f"{ent.scope_type}_id", "") or ""),
            "source": "explicit_grant", "starts_at": grant.starts_at,
            "expires_at": grant.expires_at,
        })
    for sub in subscriptions:
        for item in sub.plan.plan_entitlements.all():
            ent = item.entitlement
            if ent.is_active:
                scopes.append({
                    "name": ent.name, "scope_type": ent.scope_type,
                    "scope_id": str(getattr(ent, f"{ent.scope_type}_id", "") or ""),
                    "source": "subscription", "starts_at": sub.starts_at,
                    "expires_at": sub.expires_at,
                    "selected_subjects": [str(s.pk) for s in sub.selected_subjects.all()],
                })
    latest = (Subscription.objects.filter(user=user, study_enrollment=enrollment)
              .select_related("plan", "academic_year").prefetch_related("selected_subjects")
              .order_by("-expires_at").first()) if enrollment else None
    return free, {
        "status": "ENTITLED" if grants or subscriptions else "EXPIRED" if expired else "FREE",
        "synced_at": timezone.now(),
        "grade": enrollment.grade.name_ar if enrollment else None,
        "section": enrollment.section.name_ar if enrollment else None,
        "scopes": scopes,
        "free_subjects": [{
            "subject_id": str(p.subject_id), "subject_name": p.subject.name_ar,
            "free_unit_id": str(p.free_unit_id) if p.free_unit_id else None,
            "subject_summaries_free": p.subject_summaries_free,
            "free_ministerial_count": p.free_ministerial_count,
            "free_subject_training_count": p.free_subject_training_count,
        } for p in policies if p.subject_id],
    }, latest
