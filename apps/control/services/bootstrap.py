"""
Idempotent bootstrapping for Operations Console staff groups and permissions.
"""

import logging
from django.contrib.auth.models import Group, Permission
from django.db import transaction

logger = logging.getLogger("control.bootstrap")

STAFF_GROUP_NAME = "Staff"

# Baseline operational permission codenames for the general Staff group
STAFF_BASELINE_PERMISSIONS = [
    # Curriculum: View operational curriculum trees
    ("curriculum", "view_subject"),
    ("curriculum", "view_unit"),
    ("curriculum", "view_lesson"),
    # Content: Operational authoring
    ("content", "view_lessonexplanation"),
    ("content", "add_lessonexplanation"),
    ("content", "change_lessonexplanation"),
    ("content", "view_summary"),
    ("content", "add_summary"),
    ("content", "change_summary"),
    ("content", "view_flashcarddeck"),
    ("content", "add_flashcarddeck"),
    ("content", "change_flashcarddeck"),
    ("content", "view_flashcard"),
    ("content", "add_flashcard"),
    ("content", "change_flashcard"),
    # Question Bank: Authoring & inspection
    ("question_bank", "view_question"),
    ("question_bank", "add_question"),
    ("question_bank", "change_question"),
    ("question_bank", "view_questionversion"),
    ("question_bank", "add_questionversion"),
    ("question_bank", "change_questionversion"),
    ("question_bank", "view_questionoption"),
    ("question_bank", "view_questionasset"),
    ("question_bank", "review_question"),
    ("question_bank", "publish_question"),
    ("question_bank", "retire_question"),
    # Ministerial Exams: View & arrange
    ("ministerial_exams", "view_ministerialexam"),
    ("ministerial_exams", "view_ministerialexamitem"),
    ("ministerial_exams", "change_ministerialexam"),
    # Assessments & Training
    ("assessments", "view_assessment"),
    ("assessments", "view_trainingbatch"),
    ("assessments", "change_trainingbatch"),
    ("assessments", "view_assessmentblueprintversion"),
    ("assessments", "change_assessmentblueprintversion"),
    # Imports: View logs & execute imports
    ("imports", "view_contentimportlog"),
    ("imports", "execute_import"),
    # Subscriptions & Activation
    ("subscriptions", "view_subscription"),
    ("subscriptions", "view_subscriptionplan"),
    ("subscriptions", "view_activationcodebatch"),
    ("subscriptions", "view_activationcode"),
    ("subscriptions", "direct_activate_subscription"),
    ("subscriptions", "generate_code_batch"),
    # Accounts: Support reads & session revocation
    ("accounts", "view_user"),
    ("accounts", "view_studentprofile"),
    ("accounts", "view_userdevice"),
    ("accounts", "revoke_usersession"),
    # Notifications: Draft, edit, schedule
    ("notifications", "view_notification"),
    ("notifications", "add_notification"),
    ("notifications", "change_notification"),
    ("notifications", "publish_notification"),
    # Central Audit Log & System Health (ADM-09)
    ("control", "view_controlauditlog"),
]

# Explicit forbidden codenames for Staff (Super Admin only)
FORBIDDEN_STAFF_CODENAMES = {
    # Auth & credential management
    "add_user", "change_user", "delete_user",
    "add_group", "change_group", "delete_group",
    "add_permission", "change_permission", "delete_permission",
    # Commercial pricing & policies
    "add_subscriptionplan", "change_subscriptionplan", "delete_subscriptionplan",
    "add_freeaccesspolicy", "change_freeaccesspolicy", "delete_freeaccesspolicy",
    "add_entitlement", "change_entitlement", "delete_entitlement",
    # Technical & sync internals
    "delete_syncoperation", "delete_syncbatchreceipt", "delete_syncchange",
    "delete_pushdelivery", "delete_pushdevice",
    # Audit log protection (Append-only)
    "add_controlauditlog", "change_controlauditlog", "delete_controlauditlog",
}


class BootstrapResult(dict):
    """Result object supporting dict access and tuple unpacking (group, created)."""
    def __iter__(self):
        yield self["group"]
        yield self["created"]


@transaction.atomic
def ensure_staff_group():
    """
    Ensure the 'Staff' group exists and has exactly the baseline operational
    permissions assigned, without granting dangerous Super Admin permissions.
    Idempotent: safe to run multiple times.
    """
    group, created = Group.objects.get_or_create(name=STAFF_GROUP_NAME)

    permissions_to_assign = []
    missing_permissions = []

    for app_label, codename in STAFF_BASELINE_PERMISSIONS:
        if codename in FORBIDDEN_STAFF_CODENAMES:
            logger.warning(
                "Skipping forbidden codename '%s' for Staff group", codename
            )
            continue
        try:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
            permissions_to_assign.append(perm)
        except Permission.DoesNotExist:
            missing_permissions.append(f"{app_label}.{codename}")

    if missing_permissions:
        logger.warning(
            "Some baseline permissions were not found in the DB (migrations pending?): %s",
            missing_permissions,
        )

    # Assign permissions safely
    group.permissions.set(permissions_to_assign)

    logger.info(
        "Staff group synchronized successfully (created=%s, permissions_count=%d)",
        created,
        len(permissions_to_assign),
    )

    return BootstrapResult({
        "group": group,
        "created": created,
        "assigned_count": len(permissions_to_assign),
        "missing": missing_permissions,
    })
