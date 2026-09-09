"""
Operations Console views for Curriculum and Content workspace (/control/content/).
Provides contextual browsing and authoring for Explanations, Summaries, and Flashcards.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.generic import DetailView, FormView, TemplateView, UpdateView

from apps.content.models import (
    ContentFormat,
    Flashcard,
    FlashcardDeck,
    LessonExplanation,
    Summary,
    SummaryType,
)
from apps.control.forms.content_forms import (
    FlashcardControlForm,
    FlashcardDeckControlForm,
    LessonExplanationControlForm,
    SummaryControlForm,
)
from apps.control.permissions import ControlPermissionRequiredMixin, StaffRequiredMixin
from apps.curriculum.models import AcademicYear, ContentStatus, Grade, Lesson, Section, Subject, Unit


# ─── 1. Content Home (Hierarchy Explorer) ──────────────────────────────────

class ContentHomeView(ControlPermissionRequiredMixin, TemplateView):
    """
    Main entry point for Curriculum & Content (/control/content/).
    Allows filtering by Grade and Section, displaying subjects with aggregated content metrics.
    """
    permission_required = "curriculum.view_subject"
    template_name = "control/content/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grade_id = self.request.GET.get("grade")
        section_id = self.request.GET.get("section")
        search_query = self.request.GET.get("q", "").strip()

        grades = Grade.objects.filter(is_active=True).prefetch_related("sections").order_by("sort_order")
        active_year = AcademicYear.objects.filter(status="active").first()

        subjects_qs = (
            Subject.objects.select_related("grade", "section")
            .annotate(
                units_count=Count("units", distinct=True),
                lessons_count=Count("units__lessons", distinct=True),
                summaries_count=Count("summaries", distinct=True),
                decks_count=Count("flashcard_decks", distinct=True),
            )
            .order_by("sort_order", "id")
        )

        if grade_id:
            subjects_qs = subjects_qs.filter(grade_id=grade_id)
        if section_id:
            subjects_qs = subjects_qs.filter(section_id=section_id)
        if search_query:
            subjects_qs = subjects_qs.filter(name_ar__icontains=search_query)

        available_sections = []
        if grade_id:
            selected_grade = grades.filter(id=grade_id).first()
            if selected_grade:
                available_sections = selected_grade.sections.filter(is_active=True).order_by("sort_order")
        else:
            available_sections = Section.objects.filter(is_active=True).order_by("sort_order")

        context.update({
            "page_title": "المحتوى الدراسي",
            "active_tab": "content",
            "active_year": active_year,
            "grades": grades,
            "available_sections": available_sections,
            "selected_grade_id": grade_id,
            "selected_section_id": section_id,
            "search_query": search_query,
            "subjects": subjects_qs,
        })
        return context


# ─── 2. Subject Workspace ──────────────────────────────────────────────────

class SubjectWorkspaceView(ControlPermissionRequiredMixin, DetailView):
    """
    Subject workspace (/control/content/subjects/<subject_id>/).
    Displays subject info, list of units with lesson counts, and subject-level summaries.
    """
    permission_required = "curriculum.view_subject"
    model = Subject
    pk_url_kwarg = "subject_id"
    template_name = "control/content/subject_workspace.html"
    context_object_name = "subject"

    def get_queryset(self):
        return Subject.objects.select_related("grade", "section")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subject = self.object

        units = (
            Unit.objects.filter(subject=subject)
            .select_related("term")
            .annotate(
                lesson_count=Count("lessons", distinct=True),
                summary_count=Count("summaries", distinct=True),
            )
            .order_by("sort_order", "id")
        )

        # Subject-level summaries (subject summaries & final reviews)
        subject_summaries = (
            Summary.objects.filter(
                subject=subject,
                summary_type__in=[SummaryType.SUBJECT, SummaryType.FINAL_REVIEW],
            )
            .order_by("sort_order", "-created_at")
        )

        # Quick metrics for subject
        total_lessons = sum(u.lesson_count for u in units)
        published_summaries = Summary.objects.filter(subject=subject, status=ContentStatus.PUBLISHED).count()
        draft_summaries = Summary.objects.filter(subject=subject, status=ContentStatus.DRAFT).count()
        decks_count = FlashcardDeck.objects.filter(subject=subject).count()
        cards_count = Flashcard.objects.filter(deck__subject=subject).count()

        context.update({
            "page_title": f"مادة {subject.name_ar}",
            "active_tab": "content",
            "units": units,
            "subject_summaries": subject_summaries,
            "total_lessons": total_lessons,
            "published_summaries": published_summaries,
            "draft_summaries": draft_summaries,
            "decks_count": decks_count,
            "cards_count": cards_count,
        })
        return context


# ─── 3. Unit Workspace ────────────────────────────────────────────────────

class UnitWorkspaceView(ControlPermissionRequiredMixin, DetailView):
    """
    Unit workspace (/control/content/units/<unit_id>/).
    Displays unit info, lessons list with content status indicators, and unit-level summaries.
    """
    permission_required = "curriculum.view_unit"
    model = Unit
    pk_url_kwarg = "unit_id"
    template_name = "control/content/unit_workspace.html"
    context_object_name = "unit"

    def get_queryset(self):
        return Unit.objects.select_related("subject", "subject__grade", "subject__section", "term")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unit = self.object

        lessons = (
            Lesson.objects.filter(unit=unit)
            .annotate(
                summary_count=Count("summaries", distinct=True),
                deck_count=Count("flashcard_decks", distinct=True),
            )
            .prefetch_related("explanation")
            .order_by("sort_order", "id")
        )

        unit_summaries = (
            Summary.objects.filter(
                unit=unit,
                summary_type=SummaryType.UNIT,
            )
            .order_by("sort_order", "-created_at")
        )

        context.update({
            "page_title": f"{unit.title} — {unit.subject.name_ar}",
            "active_tab": "content",
            "lessons": lessons,
            "unit_summaries": unit_summaries,
        })
        return context


# ─── 4. Lesson Workspace ──────────────────────────────────────────────────

class LessonWorkspaceView(ControlPermissionRequiredMixin, DetailView):
    """
    Primary daily content workspace (/control/content/lessons/<lesson_id>/).
    Features tabs for:
      - الشرح (LessonExplanation)
      - الملخصات (Summaries & Quick Reviews)
      - البطاقات الذكية (Flashcard Decks & Cards)
    """
    permission_required = "curriculum.view_lesson"
    model = Lesson
    pk_url_kwarg = "lesson_id"
    template_name = "control/content/lesson_workspace.html"
    context_object_name = "lesson"

    def get_queryset(self):
        return Lesson.objects.select_related(
            "unit",
            "unit__subject",
            "unit__subject__grade",
            "unit__subject__section",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lesson = self.object
        active_tab = self.request.GET.get("tab", "explanation")

        explanation = getattr(lesson, "explanation", None)
        summaries = (
            Summary.objects.filter(lesson=lesson)
            .order_by("sort_order", "-created_at")
        )
        decks = (
            FlashcardDeck.objects.filter(lesson=lesson)
            .annotate(card_count=Count("cards", distinct=True))
            .order_by("sort_order", "-created_at")
        )

        context.update({
            "page_title": f"{lesson.title} — {lesson.unit.subject.name_ar}",
            "active_tab": "content",
            "current_tab": active_tab,
            "explanation": explanation,
            "summaries": summaries,
            "decks": decks,
        })
        return context


# ─── 5. Summary Management Views ──────────────────────────────────────────

class SummaryCreateView(ControlPermissionRequiredMixin, FormView):
    """
    Create a new Summary with contextual hierarchy pre-fill.
    """
    permission_required = "content.add_summary"
    template_name = "control/content/summary_form.html"
    form_class = SummaryControlForm

    def get_hierarchy_context(self):
        lesson_id = self.request.GET.get("lesson_id")
        unit_id = self.request.GET.get("unit_id")
        subject_id = self.request.GET.get("subject_id")

        lesson = Lesson.objects.filter(id=lesson_id).select_related("unit", "unit__subject").first() if lesson_id else None
        unit = Unit.objects.filter(id=unit_id).select_related("subject").first() if unit_id else (lesson.unit if lesson else None)
        subject = Subject.objects.filter(id=subject_id).first() if subject_id else (unit.subject if unit else None)

        return {"subject": subject, "unit": unit, "lesson": lesson}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["hierarchy_context"] = self.get_hierarchy_context()
        return kwargs

    def form_valid(self, form):
        summary = form.save()
        messages.success(self.request, f"تم إنشاء الملخص '{summary.title}' بنجاح.")
        return redirect(self.get_success_url(summary))

    def get_success_url(self, summary=None):
        if summary and summary.lesson:
            return f"{reverse('control:lesson_workspace', kwargs={'lesson_id': summary.lesson.id})}?tab=summaries"
        elif summary and summary.unit:
            return reverse("control:unit_workspace", kwargs={"unit_id": summary.unit.id})
        elif summary and summary.subject:
            return reverse("control:subject_workspace", kwargs={"subject_id": summary.subject.id})
        return reverse("control:content_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "إضافة ملخص جديد",
            "active_tab": "content",
            "is_create": True,
            "hierarchy": self.get_hierarchy_context(),
        })
        return context


class SummaryUpdateView(ControlPermissionRequiredMixin, UpdateView):
    """
    Edit an existing Summary.
    """
    permission_required = "content.change_summary"
    model = Summary
    form_class = SummaryControlForm
    template_name = "control/content/summary_form.html"
    context_object_name = "summary"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["hierarchy_context"] = {
            "subject": self.object.subject,
            "unit": self.object.unit,
            "lesson": self.object.lesson,
        }
        return kwargs

    def form_valid(self, form):
        summary = form.save()
        messages.success(self.request, f"تم تحديث الملخص '{summary.title}' بنجاح.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        summary = self.object
        if summary.lesson:
            return f"{reverse('control:lesson_workspace', kwargs={'lesson_id': summary.lesson.id})}?tab=summaries"
        elif summary.unit:
            return reverse("control:unit_workspace", kwargs={"unit_id": summary.unit.id})
        elif summary.subject:
            return reverse("control:subject_workspace", kwargs={"subject_id": summary.subject.id})
        return reverse("control:content_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"تعديل الملخص: {self.object.title}",
            "active_tab": "content",
            "is_create": False,
            "hierarchy": {
                "subject": self.object.subject,
                "unit": self.object.unit,
                "lesson": self.object.lesson,
            },
        })
        return context


class SummaryPreviewView(ControlPermissionRequiredMixin, DetailView):
    """
    Student-like semantic reader preview for a Summary.
    """
    permission_required = "content.view_summary"
    model = Summary
    template_name = "control/content/summary_preview.html"
    context_object_name = "summary"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"معاينة: {self.object.title}",
            "active_tab": "content",
        })
        return context


class SummaryStatusToggleView(ControlPermissionRequiredMixin, View):
    """
    Quick status toggle or archive action for a Summary.
    """
    permission_required = "content.change_summary"

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        summary = get_object_or_404(Summary, pk=pk)
        new_status = request.POST.get("status")
        if new_status in ContentStatus.values:
            summary.status = new_status
            summary.save(update_fields=["status", "updated_at"])
            messages.success(request, f"تم تغيير حالة الملخص إلى '{summary.get_status_display()}'.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("control:content_home"))


# ─── 6. Lesson Explanation Views ──────────────────────────────────────────

class LessonExplanationEditView(ControlPermissionRequiredMixin, View):
    """
    Create or edit the OneToOne LessonExplanation.
    """
    permission_required = "content.change_lessonexplanation"
    template_name = "control/content/explanation_form.html"

    def get_lesson(self, lesson_id):
        return get_object_or_404(
            Lesson.objects.select_related("unit", "unit__subject"),
            id=lesson_id,
        )

    def get(self, request, lesson_id):
        lesson = self.get_lesson(lesson_id)
        explanation = getattr(lesson, "explanation", None)
        form = LessonExplanationControlForm(instance=explanation)
        return render(request, self.template_name, {
            "page_title": f"شرح درس: {lesson.title}",
            "active_tab": "content",
            "lesson": lesson,
            "explanation": explanation,
            "form": form,
        })

    @method_decorator(csrf_protect)
    def post(self, request, lesson_id):
        lesson = self.get_lesson(lesson_id)
        explanation = getattr(lesson, "explanation", None)
        form = LessonExplanationControlForm(request.POST, instance=explanation)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.lesson = lesson
            exp.save()
            messages.success(request, "تم حفظ شرح الدرس بنجاح.")
            return redirect(f"{reverse('control:lesson_workspace', kwargs={'lesson_id': lesson.id})}?tab=explanation")

        return render(request, self.template_name, {
            "page_title": f"شرح درس: {lesson.title}",
            "active_tab": "content",
            "lesson": lesson,
            "explanation": explanation,
            "form": form,
        })


class LessonExplanationPreviewView(ControlPermissionRequiredMixin, View):
    """
    Semantic student-like preview for LessonExplanation.
    """
    permission_required = "content.view_lessonexplanation"
    template_name = "control/content/explanation_preview.html"

    def get(self, request, lesson_id):
        lesson = get_object_or_404(
            Lesson.objects.select_related("unit", "unit__subject"),
            id=lesson_id,
        )
        explanation = getattr(lesson, "explanation", None)
        return render(request, self.template_name, {
            "page_title": f"معاينة شرح: {lesson.title}",
            "active_tab": "content",
            "lesson": lesson,
            "explanation": explanation,
        })


# ─── 7. Flashcard Deck & Cards Views ──────────────────────────────────────

class FlashcardDeckCreateView(ControlPermissionRequiredMixin, FormView):
    """
    Create a new FlashcardDeck associated with a lesson.
    """
    permission_required = "content.add_flashcarddeck"
    template_name = "control/content/deck_form.html"
    form_class = FlashcardDeckControlForm

    def get_lesson(self):
        lesson_id = self.request.GET.get("lesson_id")
        return get_object_or_404(Lesson.objects.select_related("unit", "unit__subject"), id=lesson_id) if lesson_id else None

    def form_valid(self, form):
        lesson = self.get_lesson()
        deck = form.save(commit=False)
        if lesson:
            deck.lesson = lesson
            deck.unit = lesson.unit
            deck.subject = lesson.unit.subject
        deck.save()
        messages.success(self.request, f"تم إنشاء حزمة البطاقات '{deck.title}' بنجاح.")
        return redirect(reverse("control:deck_detail", kwargs={"pk": deck.pk}))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lesson = self.get_lesson()
        context.update({
            "page_title": "إضافة حزمة بطاقات جديدة",
            "active_tab": "content",
            "lesson": lesson,
            "is_create": True,
        })
        return context


class FlashcardDeckUpdateView(ControlPermissionRequiredMixin, UpdateView):
    """
    Edit deck title, description, and status.
    """
    permission_required = "content.change_flashcarddeck"
    model = FlashcardDeck
    form_class = FlashcardDeckControlForm
    template_name = "control/content/deck_form.html"
    context_object_name = "deck"

    def form_valid(self, form):
        deck = form.save()
        messages.success(self.request, f"تم تحديث حزمة البطاقات '{deck.title}' بنجاح.")
        return redirect(reverse("control:deck_detail", kwargs={"pk": deck.pk}))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"تعديل حزمة: {self.object.title}",
            "active_tab": "content",
            "is_create": False,
        })
        return context


class FlashcardDeckDetailView(ControlPermissionRequiredMixin, DetailView):
    """
    Deck workspace (/control/content/decks/<deck_id>/).
    Lists all cards in the deck with sort orders, actions, and preview triggers.
    """
    permission_required = "content.view_flashcarddeck"
    model = FlashcardDeck
    template_name = "control/content/deck_detail.html"
    context_object_name = "deck"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        deck = self.object
        cards = deck.cards.order_by("sort_order", "id")
        context.update({
            "page_title": f"حزمة: {deck.title}",
            "active_tab": "content",
            "cards": cards,
        })
        return context


class FlashcardCreateView(ControlPermissionRequiredMixin, FormView):
    """
    Add a new card to a specific deck.
    """
    permission_required = "content.add_flashcard"
    template_name = "control/content/flashcard_form.html"
    form_class = FlashcardControlForm

    def get_deck(self):
        return get_object_or_404(FlashcardDeck, pk=self.kwargs["deck_pk"])

    def form_valid(self, form):
        deck = self.get_deck()
        card = form.save(commit=False)
        card.deck = deck
        # Auto-assign next sort order if not specified
        if card.sort_order == 0:
            last_order = deck.cards.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
            card.sort_order = last_order + 1
        card.save()
        messages.success(self.request, "تمت إضافة البطاقة التعليمية بنجاح.")
        return redirect(reverse("control:deck_detail", kwargs={"pk": deck.pk}))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        deck = self.get_deck()
        context.update({
            "page_title": f"إضافة بطاقة إلى: {deck.title}",
            "active_tab": "content",
            "deck": deck,
            "is_create": True,
        })
        return context


class FlashcardUpdateView(ControlPermissionRequiredMixin, UpdateView):
    """
    Edit an existing flashcard.
    """
    permission_required = "content.change_flashcard"
    model = Flashcard
    form_class = FlashcardControlForm
    template_name = "control/content/flashcard_form.html"
    context_object_name = "card"

    def form_valid(self, form):
        card = form.save()
        messages.success(self.request, "تم تحديث البطاقة التعليمية بنجاح.")
        return redirect(reverse("control:deck_detail", kwargs={"pk": card.deck.pk}))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "تعديل البطاقة التعليمية",
            "active_tab": "content",
            "deck": self.object.deck,
            "is_create": False,
        })
        return context


class FlashcardPreviewView(ControlPermissionRequiredMixin, DetailView):
    """
    Interactive 3D flip preview for a flashcard.
    """
    permission_required = "content.view_flashcard"
    model = Flashcard
    template_name = "control/content/flashcard_preview.html"
    context_object_name = "card"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"معاينة بطاقة — {self.object.deck.title}",
            "active_tab": "content",
        })
        return context
