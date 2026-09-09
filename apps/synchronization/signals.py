import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.curriculum.models import Grade, Section, Subject, Unit, Lesson
from apps.content.models import Summary, FlashcardDeck, ContentLink, LessonExplanation
from apps.synchronization.models import SyncChange, SyncChangeAction

logger = logging.getLogger("synchronization.signals")

TRACKED_MODELS = [Grade, Section, Subject, Unit, Lesson, Summary, FlashcardDeck, ContentLink, LessonExplanation]


def _record_sync_change(sender, instance, action: str):
    """
    Helper function to record a SyncChange entry on commit.
    """
    resource_type = sender._meta.model_name
    resource_id = str(instance.pk)
    resource_version = str(getattr(instance, "version", 1))

    # Resolve scopes
    grade = getattr(instance, "grade", None)
    section = getattr(instance, "section", None)
    subject = getattr(instance, "subject", None)
    unit = getattr(instance, "unit", None)
    lesson = getattr(instance, "lesson", None)

    # Scopes resolution from parent relationships if needed
    if not subject and unit:
        subject = getattr(unit, "subject", None)
    if not subject and lesson:
        subject = getattr(lesson, "subject", None)
    if not unit and lesson:
        unit = getattr(lesson, "unit", None)

    title = getattr(instance, "title", str(instance))
    metadata = {
        "title": title[:200] if title else "",
        "updated_at": instance.updated_at.isoformat() if hasattr(instance, "updated_at") and instance.updated_at else timezone.now().isoformat(),
    }

    def _do_create():
        try:
            SyncChange.objects.create(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                grade=grade if isinstance(grade, Grade) else None,
                section=section if isinstance(section, Section) else None,
                subject=subject if isinstance(subject, Subject) else None,
                unit=unit if isinstance(unit, Unit) else None,
                lesson=lesson if isinstance(lesson, Lesson) else None,
                resource_version=resource_version,
                metadata_snapshot=metadata,
                changed_at=timezone.now(),
            )
        except Exception as e:
            logger.warning(f"Failed to record SyncChange for {resource_type}:{resource_id}: {e}")

    transaction.on_commit(_do_create)


@receiver(post_save, sender=Grade)
@receiver(post_save, sender=Section)
@receiver(post_save, sender=Subject)
@receiver(post_save, sender=Unit)
@receiver(post_save, sender=Lesson)
@receiver(post_save, sender=Summary)
@receiver(post_save, sender=FlashcardDeck)
@receiver(post_save, sender=ContentLink)
@receiver(post_save, sender=LessonExplanation)
def content_post_save_receiver(sender, instance, created, **kwargs):
    action = SyncChangeAction.UPSERT
    if hasattr(instance, "is_published") and not instance.is_published:
        action = SyncChangeAction.ARCHIVE
    _record_sync_change(sender, instance, action)


@receiver(post_delete, sender=Grade)
@receiver(post_delete, sender=Section)
@receiver(post_delete, sender=Subject)
@receiver(post_delete, sender=Unit)
@receiver(post_delete, sender=Lesson)
@receiver(post_delete, sender=Summary)
@receiver(post_delete, sender=FlashcardDeck)
@receiver(post_delete, sender=ContentLink)
@receiver(post_delete, sender=LessonExplanation)
def content_post_delete_receiver(sender, instance, **kwargs):
    _record_sync_change(sender, instance, SyncChangeAction.DELETE)
