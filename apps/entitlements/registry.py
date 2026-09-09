import logging
from typing import Dict, Any, Optional

from apps.curriculum.models import Subject, Unit, Lesson
from apps.content.models import LessonExplanation, Summary, FlashcardDeck, Flashcard, ContentLink
from apps.assessments.models import Assessment, TrainingBatch
from apps.ministerial_exams.models import MinisterialExam

logger = logging.getLogger("entitlements.registry")


def _content_scope(resource) -> Optional[Dict[str, Optional[str]]]:
    """Resolve the most specific published curriculum parent for content."""
    lesson = getattr(resource, "lesson", None)
    unit = lesson.unit if lesson else getattr(resource, "unit", None)
    subject = unit.subject if unit else getattr(resource, "subject", None)

    if not subject or subject.status != "published":
        return None
    if unit and unit.status != "published":
        return None
    if lesson and lesson.status != "published":
        return None

    return {
        "grade_id": str(subject.grade_id),
        "section_id": str(subject.section_id),
        "subject_id": str(subject.id),
        "unit_id": str(unit.id) if unit else None,
        "lesson_id": str(lesson.id) if lesson else None,
        "assessment_id": None,
    }


class ResourceAccessRegistry:
    """
    Centralized registry linking every system resource type to its DB Model,
    academic scope extraction logic, publication status check, and free unit applicability.
    """

    @classmethod
    def resolve_resources_batch(cls, resources: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
        """
        Resolves resource metadata, academic scope, publication status, and free unit eligibility in bulk.
        Groups resources by type to execute at most 1 query per resource type.
        """
        results: dict[tuple[str, str], dict[str, Any]] = {}
        if not resources:
            return results

        grouped: dict[str, set[str]] = {}
        for r in resources:
            res_type = r.get("resource_type") or r.get("type")
            res_id = str(r.get("resource_id") or r.get("id"))
            if res_type and res_id:
                grouped.setdefault(res_type, set()).add(res_id)

        for res_type, ids in grouped.items():
            if res_type == "subject":
                subjs = Subject.objects.filter(id__in=ids, status="published")
                for subj in subjs:
                    results[("subject", str(subj.id))] = {
                        "resource_type": "subject",
                        "resource_id": str(subj.id),
                        "is_published": True,
                        "applies_free_unit": False,
                        "scope": {
                            "grade_id": str(subj.grade_id),
                            "section_id": str(subj.section_id),
                            "subject_id": str(subj.id),
                            "unit_id": None,
                            "assessment_id": None,
                        },
                    }

            elif res_type == "unit":
                units = Unit.objects.filter(id__in=ids, status="published", subject__status="published").select_related(
                    "subject", "subject__grade", "subject__section"
                )
                for unit in units:
                    results[("unit", str(unit.id))] = {
                        "resource_type": "unit",
                        "resource_id": str(unit.id),
                        "is_published": True,
                        "applies_free_unit": True,
                        "scope": {
                            "grade_id": str(unit.subject.grade_id),
                            "section_id": str(unit.subject.section_id),
                            "subject_id": str(unit.subject_id),
                            "unit_id": str(unit.id),
                            "assessment_id": None,
                        },
                    }

            elif res_type == "lesson":
                lessons = Lesson.objects.filter(
                    id__in=ids, status="published", unit__status="published", unit__subject__status="published"
                ).select_related("unit", "unit__subject", "unit__subject__grade", "unit__subject__section")
                for lesson in lessons:
                    results[("lesson", str(lesson.id))] = {
                        "resource_type": "lesson",
                        "resource_id": str(lesson.id),
                        "is_published": True,
                        "applies_free_unit": True,
                        "scope": {
                            "grade_id": str(lesson.unit.subject.grade_id),
                            "section_id": str(lesson.unit.subject.section_id),
                            "subject_id": str(lesson.unit.subject_id),
                            "unit_id": str(lesson.unit_id),
                            "lesson_id": str(lesson.id),
                            "assessment_id": None,
                        },
                    }

            elif res_type == "lesson_explanation":
                exps = LessonExplanation.objects.filter(
                    id__in=ids, status="published", lesson__status="published", lesson__unit__status="published", lesson__unit__subject__status="published"
                ).select_related("lesson", "lesson__unit", "lesson__unit__subject", "lesson__unit__subject__grade", "lesson__unit__subject__section")
                for exp in exps:
                    lesson = exp.lesson
                    results[("lesson_explanation", str(exp.id))] = {
                        "resource_type": "lesson_explanation",
                        "resource_id": str(exp.id),
                        "is_published": True,
                        "applies_free_unit": True,
                        "scope": {
                            "grade_id": str(lesson.unit.subject.grade_id),
                            "section_id": str(lesson.unit.subject.section_id),
                            "subject_id": str(lesson.unit.subject_id),
                            "unit_id": str(lesson.unit_id),
                            "lesson_id": str(lesson.id),
                            "assessment_id": None,
                        },
                    }

            elif res_type == "summary":
                summs = Summary.objects.filter(
                    id__in=ids, status="published"
                ).select_related(
                    "subject",
                    "unit",
                    "unit__subject",
                    "lesson",
                    "lesson__unit",
                    "lesson__unit__subject",
                )
                for summ in summs:
                    scope = _content_scope(summ)
                    if scope is None:
                        continue
                    results[("summary", str(summ.id))] = {
                        "resource_type": "summary",
                        "resource_id": str(summ.id),
                        "version": str(summ.version),
                        "is_published": True,
                        "applies_free_unit": scope["unit_id"] is not None,
                        "scope": scope,
                    }

            elif res_type == "flashcard_deck":
                decks = FlashcardDeck.objects.filter(
                    id__in=ids, status="published"
                ).select_related(
                    "subject",
                    "unit",
                    "unit__subject",
                    "lesson",
                    "lesson__unit",
                    "lesson__unit__subject",
                )
                for deck in decks:
                    scope = _content_scope(deck)
                    if scope is None:
                        continue
                    results[("flashcard_deck", str(deck.id))] = {
                        "resource_type": "flashcard_deck",
                        "resource_id": str(deck.id),
                        "is_published": True,
                        "applies_free_unit": scope["unit_id"] is not None,
                        "scope": scope,
                    }

            elif res_type in ["assessment", "lesson_practice", "unit_test"]:
                asms = Assessment.objects.filter(id__in=ids, status="published").select_related(
                    "subject", "unit", "lesson", "subject__grade", "subject__section", "lesson__unit", "ministerial_exam"
                )
                for asm in asms:
                    if asm.subject and asm.subject.status != "published":
                        continue
                    if (asm.unit and asm.unit.status != "published") or (asm.lesson and (
                        asm.lesson.status != "published" or asm.lesson.unit.status != "published"
                    )):
                        continue
                    applies_free = False
                    unit_id = str(asm.unit_id) if asm.unit_id else None
                    if asm.lesson_id and hasattr(asm, "lesson") and asm.lesson:
                        unit_id = str(asm.lesson.unit_id)
                    if asm.assessment_type == "lesson_practice" or (asm.unit_id or asm.lesson_id):
                        applies_free = True

                    results[(res_type, str(asm.id))] = {
                        "resource_type": res_type,
                        "resource_id": str(asm.id),
                        "is_published": True,
                        "free_access_rank": (
                            asm.ministerial_exam.free_access_rank
                            if hasattr(asm, "ministerial_exam") and asm.ministerial_exam
                            else None
                        ),
                        "applies_free_unit": applies_free,
                        "scope": {
                            "grade_id": str(asm.subject.grade_id) if asm.subject else None,
                            "section_id": str(asm.subject.section_id) if asm.subject else None,
                            "subject_id": str(asm.subject_id) if asm.subject_id else None,
                            "unit_id": unit_id,
                            "lesson_id": str(asm.lesson_id) if asm.lesson_id else None,
                            "assessment_id": str(asm.id),
                        },
                    }
            else:
                for rid in ids:
                    data = cls.resolve_resource(res_type, rid)
                    if data:
                        results[(res_type, rid)] = data

        return results

    @classmethod
    def resolve_resource(cls, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """
        Resolves resource metadata, academic scope, publication status, and free unit eligibility.
        
        Returns dict or None if resource does not exist.
        """

        try:
            if resource_type == "subject":
                subj = Subject.objects.filter(id=resource_id, status="published").first()
                if not subj:
                    return None
                return {
                    "resource_type": "subject",
                    "resource_id": str(subj.id),
                    "is_published": subj.status == "published",
                    "applies_free_unit": False,
                    "scope": {
                        "grade_id": str(subj.grade_id),
                        "section_id": str(subj.section_id),
                        "subject_id": str(subj.id),
                        "unit_id": None,
                        "assessment_id": None,
                    },
                }

            elif resource_type == "unit":
                unit = Unit.objects.filter(id=resource_id).select_related("subject", "subject__grade", "subject__section").first()
                if not unit or unit.status != "published":
                    return None
                if unit.subject.status != "published":
                    return None
                return {
                    "resource_type": "unit",
                    "resource_id": str(unit.id),
                    "is_published": True,
                    "applies_free_unit": True,
                    "scope": {
                        "grade_id": str(unit.subject.grade_id),
                        "section_id": str(unit.subject.section_id),
                        "subject_id": str(unit.subject_id),
                        "unit_id": str(unit.id),
                        "assessment_id": None,
                    },
                }

            elif resource_type == "lesson":
                lesson = Lesson.objects.filter(id=resource_id).select_related(
                    "unit", "unit__subject", "unit__subject__grade", "unit__subject__section"
                ).first()
                if not lesson or lesson.status != "published":
                    return None
                if lesson.unit.status != "published" or lesson.unit.subject.status != "published":
                    return None
                return {
                    "resource_type": "lesson",
                    "resource_id": str(lesson.id),
                    "is_published": True,
                    "applies_free_unit": True,
                    "scope": {
                        "grade_id": str(lesson.unit.subject.grade_id),
                        "section_id": str(lesson.unit.subject.section_id),
                        "subject_id": str(lesson.unit.subject_id),
                        "unit_id": str(lesson.unit_id),
                        "lesson_id": str(lesson.id),
                        "assessment_id": None,
                    },
                }

            elif resource_type == "lesson_explanation":
                exp = LessonExplanation.objects.filter(id=resource_id).select_related(
                    "lesson", "lesson__unit", "lesson__unit__subject"
                ).first()
                if not exp or exp.status != "published":
                    return None
                lesson = exp.lesson
                if lesson.status != "published" or lesson.unit.status != "published" or lesson.unit.subject.status != "published":
                    return None
                return {
                    "resource_type": "lesson_explanation",
                    "resource_id": str(exp.id),
                    "is_published": True,
                    "applies_free_unit": True,
                    "scope": {
                        "grade_id": str(lesson.unit.subject.grade_id),
                        "section_id": str(lesson.unit.subject.section_id),
                        "subject_id": str(lesson.unit.subject_id),
                        "unit_id": str(lesson.unit_id),
                        "lesson_id": str(lesson.id),
                        "assessment_id": None,
                    },
                }

            elif resource_type == "summary":
                summ = Summary.objects.filter(id=resource_id).select_related(
                    "subject",
                    "unit",
                    "unit__subject",
                    "lesson",
                    "lesson__unit",
                    "lesson__unit__subject",
                ).first()
                if not summ or summ.status != "published":
                    return None
                scope = _content_scope(summ)
                if scope is None:
                    return None
                return {
                    "resource_type": "summary",
                    "resource_id": str(summ.id),
                    "version": str(summ.version),
                    "is_published": True,
                    "applies_free_unit": scope["unit_id"] is not None,
                    "scope": scope,
                }

            elif resource_type == "flashcard_deck":
                deck = FlashcardDeck.objects.filter(id=resource_id).select_related(
                    "subject",
                    "unit",
                    "unit__subject",
                    "lesson",
                    "lesson__unit",
                    "lesson__unit__subject",
                ).first()
                if not deck or deck.status != "published":
                    return None
                scope = _content_scope(deck)
                if scope is None:
                    return None
                return {
                    "resource_type": "flashcard_deck",
                    "resource_id": str(deck.id),
                    "is_published": True,
                    "applies_free_unit": scope["unit_id"] is not None,
                    "scope": scope,
                }

            elif resource_type == "flashcard":
                card = Flashcard.objects.filter(id=resource_id).select_related(
                    "deck",
                    "deck__subject",
                    "deck__unit",
                    "deck__unit__subject",
                    "deck__lesson",
                    "deck__lesson__unit",
                    "deck__lesson__unit__subject",
                ).first()
                if not card:
                    return None
                deck = card.deck
                scope = _content_scope(deck)
                if deck.status != "published" or scope is None:
                    return None
                return {
                    "resource_type": "flashcard",
                    "resource_id": str(card.id),
                    "is_published": True,
                    "applies_free_unit": scope["unit_id"] is not None,
                    "scope": scope,
                }

            elif resource_type == "content_link":
                link = ContentLink.objects.filter(id=resource_id).select_related(
                    "subject",
                    "unit",
                    "unit__subject",
                    "lesson",
                    "lesson__unit",
                    "lesson__unit__subject",
                ).first()
                if not link or link.status != "published":
                    return None
                scope = _content_scope(link)
                if scope is None:
                    return None
                return {
                    "resource_type": "content_link",
                    "resource_id": str(link.id),
                    "is_published": True,
                    "applies_free_unit": scope["unit_id"] is not None,
                    "scope": scope,
                }

            elif resource_type in ["assessment", "lesson_practice", "unit_test"]:
                asm = Assessment.objects.filter(id=resource_id, status="published").select_related(
                    "subject", "unit", "lesson", "subject__grade", "subject__section", "ministerial_exam"
                ).first()
                if not asm:
                    return None
                if asm.subject and asm.subject.status != "published":
                    return None
                if (asm.unit and asm.unit.status != "published") or (asm.lesson and (
                    asm.lesson.status != "published" or asm.lesson.unit.status != "published"
                )):
                    return None
                
                applies_free = False
                unit_id = str(asm.unit_id) if asm.unit_id else None
                if asm.lesson_id and hasattr(asm, "lesson") and asm.lesson:
                    unit_id = str(asm.lesson.unit_id)

                if asm.assessment_type == "lesson_practice" or (asm.unit_id or asm.lesson_id):
                    applies_free = True

                return {
                    "resource_type": resource_type,
                    "resource_id": str(asm.id),
                    "is_published": True,
                    "free_access_rank": (
                        asm.ministerial_exam.free_access_rank
                        if hasattr(asm, "ministerial_exam") and asm.ministerial_exam
                        else None
                    ),
                    "applies_free_unit": applies_free,
                    "scope": {
                        "grade_id": str(asm.subject.grade_id) if asm.subject else None,
                        "section_id": str(asm.subject.section_id) if asm.subject else None,
                        "subject_id": str(asm.subject_id) if asm.subject_id else None,
                        "unit_id": unit_id,
                        "lesson_id": str(asm.lesson_id) if asm.lesson_id else None,
                        "assessment_id": str(asm.id),
                    },
                }

            elif resource_type == "ministerial_exam":
                m_exam = MinisterialExam.objects.filter(id=resource_id, status="published").select_related(
                    "subject", "subject__grade", "subject__section", "assessment"
                ).first()
                if not m_exam or m_exam.subject.status != "published":
                    return None
                
                assessment_id = str(m_exam.assessment_id) if m_exam.assessment_id else None
                return {
                    "resource_type": "ministerial_exam",
                    "resource_id": str(m_exam.id),
                    "is_published": True,
                    "free_access_rank": m_exam.free_access_rank,
                    "applies_free_unit": False,
                    "scope": {
                        "grade_id": str(m_exam.subject.grade_id),
                        "section_id": str(m_exam.subject.section_id),
                        "subject_id": str(m_exam.subject_id),
                        "unit_id": None,
                        "assessment_id": assessment_id,
                    },
                }

            elif resource_type == "training_batch":
                batch = TrainingBatch.objects.filter(id=resource_id).select_related(
                    "subject", "unit", "lesson"
                ).first()
                if not batch or batch.subject.status != "published":
                    return None
                if (batch.unit and batch.unit.status != "published") or (batch.lesson and (
                    batch.lesson.status != "published" or batch.lesson.unit.status != "published"
                )):
                    return None
                return {
                    "resource_type": "training_batch",
                    "resource_id": str(batch.id),
                    "is_published": True,
                    "free_access_rank": batch.free_access_rank,
                    "applies_free_unit": bool(batch.unit_id),
                    "scope": {
                        "grade_id": str(batch.subject.grade_id),
                        "section_id": str(batch.subject.section_id),
                        "subject_id": str(batch.subject_id),
                        "unit_id": str(batch.unit_id) if batch.unit_id else None,
                        "lesson_id": str(batch.lesson_id) if batch.lesson_id else None,
                        "assessment_id": None,
                    },
                }

            elif resource_type in ["question_asset", "question_option_image", "question_stimulus", "ministerial_source_file", "protected_media"]:
                # Resolved via media access registry mapping
                from apps.media_access.registry import MediaResourceRegistry
                resource = MediaResourceRegistry.resolve_resource(resource_type, resource_id)
                if not resource:
                    return None
                
                # Check unit / lesson context if applicable
                unit_id = getattr(resource, "unit_id", None)
                subject_id = getattr(resource, "subject_id", None)
                grade_id = None
                section_id = None
                
                if hasattr(resource, "subject") and resource.subject:
                    subject_id = str(resource.subject.id)
                    grade_id = str(resource.subject.grade_id)
                    section_id = str(resource.subject.section_id)
                elif hasattr(resource, "unit") and resource.unit:
                    unit_id = str(resource.unit.id)
                    subject_id = str(resource.unit.subject_id)
                    grade_id = str(resource.unit.subject.grade_id)
                    section_id = str(resource.unit.subject.section_id)

                return {
                    "resource_type": resource_type,
                    "resource_id": str(resource_id),
                    "is_published": True,
                    "applies_free_unit": bool(unit_id),
                    "scope": {
                        "grade_id": grade_id,
                        "section_id": section_id,
                        "subject_id": subject_id,
                        "unit_id": unit_id,
                        "assessment_id": None,
                    },
                }

            else:
                logger.warning("Unknown resource_type in registry: %s", resource_type)
                return None

        except Exception as e:
            logger.exception("Error resolving resource in registry (%s, %s): %s", resource_type, resource_id, str(e))
            return None
