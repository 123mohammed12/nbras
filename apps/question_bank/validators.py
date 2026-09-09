from django.core.exceptions import ValidationError


def validate_subject_unit_lesson(subject, unit=None, lesson=None):
    """
    Validates academic containment hierarchy:
    1. Unit must belong to Subject.
    2. Lesson must belong to Unit.
    3. Derived Subject and Unit from Lesson must match Subject and Unit.
    """
    if not subject:
        raise ValidationError("المادة الدراسية مطلوبة.")

    subject_id = subject.id if hasattr(subject, "id") else subject
    unit_id = unit.id if hasattr(unit, "id") else unit
    lesson_id = lesson.id if hasattr(lesson, "id") else lesson

    if lesson:
        lesson_unit_id = lesson.unit_id if hasattr(lesson, "unit_id") else None
        lesson_subject_id = lesson.unit.subject_id if hasattr(lesson, "unit") and hasattr(lesson.unit, "subject_id") else None

        if unit_id and lesson_unit_id and str(unit_id) != str(lesson_unit_id):
            raise ValidationError("الدرس المحدد لا ينتمي إلى الوحدة الدراسية المحددة.")

        if lesson_subject_id and str(subject_id) != str(lesson_subject_id):
            raise ValidationError("الدرس المحدد لا ينتمي إلى المادة الدراسية المحددة.")

    if unit:
        unit_subject_id = unit.subject_id if hasattr(unit, "subject_id") else None
        if unit_subject_id and str(subject_id) != str(unit_subject_id):
            raise ValidationError("الوحدة الدراسية المحددة لا تنتمي إلى المادة الدراسية المحددة.")


def validate_topic_belongs_to_lesson(lesson=None, topic=None):
    """
    Validates that Topic belongs to the given Lesson.
    """
    if topic and lesson:
        topic_lesson_id = topic.lesson_id if hasattr(topic, "lesson_id") else None
        lesson_id = lesson.id if hasattr(lesson, "id") else lesson
        if topic_lesson_id and str(topic_lesson_id) != str(lesson_id):
            raise ValidationError("الموضوع التفصيلي المحدد لا ينتمي إلى الدرس المحدد.")


def validate_question_hierarchy(*, subject, unit=None, lesson=None, topic=None):
    """
    Comprehensive academic hierarchy validator for Questions.
    """
    validate_subject_unit_lesson(subject=subject, unit=unit, lesson=lesson)
    validate_topic_belongs_to_lesson(lesson=lesson, topic=topic)


def validate_stimulus_hierarchy(*, stimulus, subject, unit=None, lesson=None):
    """
    Validates that QuestionStimulus aligns with the Question's academic context.
    """
    if not stimulus:
        return

    stim_sub_id = stimulus.subject_id if hasattr(stimulus, "subject_id") else None
    sub_id = subject.id if hasattr(subject, "id") else subject

    if stim_sub_id and str(stim_sub_id) != str(sub_id):
        raise ValidationError("محتوى المحفز (Stimulus) يتبع مادة دراسية مختلفة عن مادة السؤال.")
