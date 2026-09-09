from django.apps import apps
from django.core.exceptions import ValidationError


CONTRACT = {
    "NONE": (), "OPEN_SETTINGS": (), "OPEN_SUBSCRIPTION": (),
    "OPEN_SUBJECT": ("subject_id",),
    "OPEN_UNIT": ("subject_id", "unit_id"),
    "OPEN_LESSON": ("subject_id", "unit_id", "lesson_id"),
    "OPEN_RESOURCE": ("resource_type", "resource_id"),
    "OPEN_SMART_CARDS": ("deck_id",),
    "OPEN_ATTEMPT": ("attempt_id",), "OPEN_RESULT": ("attempt_id",),
}


def validate_action(action, payload):
    if action not in CONTRACT or not isinstance(payload, dict) or set(payload) != set(CONTRACT[action]):
        raise ValidationError({"action_payload": "حقول الوجهة لا تطابق نوع الإجراء."})
    if any(not isinstance(v, str) or not v.strip() or len(v) > 100 or any(c in v for c in '/\\?#') for v in payload.values()):
        raise ValidationError({"action_payload": "معرفات الوجهة غير صالحة."})
    refs = {"subject_id": "curriculum.Subject", "unit_id": "curriculum.Unit", "lesson_id": "curriculum.Lesson", "deck_id": "content.FlashcardDeck", "attempt_id": "attempts.AssessmentAttempt"}
    objects = {}
    try:
        for key, model in refs.items():
            if key in payload:
                objects[key] = apps.get_model(model).objects.get(pk=payload[key])
        if action == "OPEN_RESOURCE":
            if payload["resource_type"] != "summary":
                raise ValueError()
            objects["resource_id"] = apps.get_model("content.Summary").objects.get(pk=payload["resource_id"])
    except (ValueError, ValidationError, LookupError):
        raise ValidationError({"action_payload": "تعذر العثور على الوجهة."})
    except Exception as exc:
        from django.core.exceptions import ObjectDoesNotExist
        if isinstance(exc, ObjectDoesNotExist):
            raise ValidationError({"action_payload": "تعذر العثور على الوجهة."}) from None
        raise
    if "unit_id" in objects and str(objects["unit_id"].subject_id) != payload["subject_id"]:
        raise ValidationError({"action_payload": "الوحدة لا تنتمي للمادة."})
    if "lesson_id" in objects and str(objects["lesson_id"].unit_id) != payload["unit_id"]:
        raise ValidationError({"action_payload": "الدرس لا ينتمي للوحدة."})
    for obj in objects.values():
        if obj._meta.app_label in ("curriculum", "content") and getattr(obj, "status", "published") != "published":
            raise ValidationError({"action_payload": "الوجهة غير منشورة."})
    return objects
