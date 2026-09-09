import json
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.control.permissions import ControlPermissionRequiredMixin
from apps.control.forms.assessment_forms import (
    MinisterialExamFilterForm,
    MinisterialItemReorderForm,
    LessonBatchFilterForm,
    TrainingBatchFilterForm,
    MockBlueprintFilterForm,
    MockBlueprintVersionDraftForm,
)
from apps.curriculum.models import Grade, Subject, Unit, Lesson, ContentStatus
from apps.ministerial_exams.models import (
    MinisterialExam,
    MinisterialExamSection,
    MinisterialExamItem,
    LessonMinisterialBatch,
    LessonMinisterialBatchItem,
    ExamRole,
)
from apps.ministerial_exams.services import (
    recalculate_exam_totals,
    validate_ministerial_exam_publishability,
    sync_lesson_ministerial_batches,
)
from apps.assessments.models import (
    Assessment,
    AssessmentVersion,
    AssessmentItem,
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    TrainingBatch,
    TrainingBatchItem,
    TrainingBatchScope,
    AssessmentType,
)
from apps.assessments.services.training import (
    sync_training_batches,
    eligible_training_question_count,
    training_scope_key,
)
from apps.attempts.services.mock_exams import (
    blueprint_pool_readiness,
    publish_blueprint_version,
)
from apps.attempts.services.selection_engine import SUPPORTED_TYPES
from apps.common.exceptions import ApplicationError
from apps.question_bank.models import Question, QuestionVersion, SourceType, DifficultyLevel


class AssessmentsHubView(ControlPermissionRequiredMixin, TemplateView):
    """
    Central hub for assessment operations and complete inventory of all 14 assessment types.
    """
    template_name = "control/assessments/hub.html"
    permission_required = "assessments.view_assessment"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "assessments"

        # KPIs
        context["ministerial_count"] = MinisterialExam.objects.count()
        context["training_batch_count"] = TrainingBatch.objects.count()
        context["mock_blueprint_count"] = AssessmentBlueprint.objects.count()
        context["curriculum_assessment_count"] = Assessment.objects.filter(
            assessment_type__in=[
                AssessmentType.LESSON_TEST,
                AssessmentType.UNIT_TEST,
                AssessmentType.SUBJECT_TEST,
            ]
        ).count()

        # Inventory catalog of all 14 types
        context["inventory_types"] = [
            {
                "name": "النماذج الوزارية الكاملة",
                "code": "ministerial_exam",
                "classification": "A. إدارة تشغيلية في ADM-05",
                "badge_class": "badge-success",
                "model": "MinisterialExam",
                "description": "امتحانات الشهادة الثانوية الرسمية مع الأقسام والعناصر والدرجات الموثقة.",
                "url": reverse("control:ministerial_list"),
            },
            {
                "name": "دفعات الدروس الوزارية",
                "code": "lesson_ministerial",
                "classification": "A. إدارة تشغيلية في ADM-05",
                "badge_class": "badge-success",
                "model": "LessonMinisterialBatch",
                "description": "دفعات أسئلة وزارية مجمعة للدروس عبر سنوات متعددة مع مزامنة رسمية.",
                "url": reverse("control:ministerial_batches"),
            },
            {
                "name": "دفعات التدريب",
                "code": "training_test",
                "classification": "A. إدارة تشغيلية في ADM-05",
                "badge_class": "badge-success",
                "model": "TrainingBatch",
                "description": "دفعات تدريبية متوازنة الصعوبة والأنواع لنطاقات الدرس والوحدة والمادة.",
                "url": reverse("control:training_list"),
            },
            {
                "name": "نماذج المحاكاة والـ Blueprints",
                "code": "mock_exam",
                "classification": "A. إدارة تشغيلية في ADM-05",
                "badge_class": "badge-success",
                "model": "AssessmentBlueprintVersion",
                "description": "مخططات اختبارات محاكاة وزارية مع دلاء اختيار دقيقة وفحص جاهزية الحوض.",
                "url": reverse("control:mock_list"),
            },
            {
                "name": "الاختبارات المخصصة",
                "code": "custom_test",
                "classification": "B/D. مراقبة وجاهزية دون CRUD",
                "badge_class": "badge-info",
                "model": "SelectionEngine (Runtime)",
                "description": "توليد لحظي مخصص بحسب اختيار الطالب؛ المحاولات مجمدة وتاريخية.",
                "url": reverse("control:custom_test_readiness"),
            },
            {
                "name": "اختبارات الدروس",
                "code": "lesson_test",
                "classification": "B. رصد ومراقبة المنهج",
                "badge_class": "badge-secondary",
                "model": "Assessment (lesson_test)",
                "description": "اختبارات موضوعة على مستوى كل درس؛ تعديل الأسئلة يتم في بنك الأسئلة ADM-03.",
                "url": None,
            },
            {
                "name": "اختبارات الوحدات",
                "code": "unit_test",
                "classification": "B. رصد ومراقبة المنهج",
                "badge_class": "badge-secondary",
                "model": "Assessment (unit_test)",
                "description": "اختبارات تغطي وحدات المنهج المعتمدة؛ تعديل الأسئلة في ADM-03.",
                "url": None,
            },
            {
                "name": "اختبارات المواد المحدودة",
                "code": "subject_test",
                "classification": "B. رصد ومراقبة المنهج",
                "badge_class": "badge-secondary",
                "model": "Assessment (subject_test)",
                "description": "اختبارات على مستوى المادة التعليمية الكاملة.",
                "url": None,
            },
            {
                "name": "اختبر نفسك",
                "code": "self_practice",
                "classification": "B. رصد ومراقبة المنهج",
                "badge_class": "badge-secondary",
                "model": "Assessment (self_practice)",
                "description": "تقييمات ذاتية ثابتة للتدريب الفردي.",
                "url": None,
            },
            {
                "name": "إعادة الأسئلة الخاطئة",
                "code": "wrong_answers_test",
                "classification": "D. توليد لحظي للطلاب — لا CRUD",
                "badge_class": "badge-warning",
                "model": "QuestionPerformanceEvidence",
                "description": "توليد ديناميكي لأسئلة أخطأ فيها الطالب؛ محاولات الطالب غير قابلة للتحرير الإداري.",
                "url": None,
            },
            {
                "name": "إعادة الأسئلة غير المجابة",
                "code": "unanswered_test",
                "classification": "D. توليد لحظي للطلاب — لا CRUD",
                "badge_class": "badge-warning",
                "model": "AssessmentAttempt (Retry)",
                "description": "إعادة الأسئلة التي لم يجب عليها الطالب في محاولته السابقة.",
                "url": None,
            },
            {
                "name": "تدريب نقاط الضعف",
                "code": "weakness_practice",
                "classification": "D. توليد لحظي للطلاب — لا CRUD",
                "badge_class": "badge-warning",
                "model": "ar06_practice Signals",
                "description": "توليد ذكي مستهدف لأبعاد الضعف في الأداء لدى الطالب.",
                "url": None,
            },
            {
                "name": "اختبار شهري",
                "code": "monthly_test",
                "classification": "E. مؤجل ومصنف",
                "badge_class": "badge-neutral",
                "model": "AssessmentType Enum",
                "description": "مدرج في بنية النظام للتوسعات المستقبلية.",
                "url": None,
            },
            {
                "name": "اختبار مجموعات / ذكاء اصطناعي",
                "code": "group_test / ai_generated_test",
                "classification": "E. مؤجل ومصنف",
                "badge_class": "badge-neutral",
                "model": "AssessmentType Enum",
                "description": "مدرج في المخطط لخارطة الطريق اللاحقة.",
                "url": None,
            },
        ]
        return context


# ==============================================================================
# MINISTERIAL EXAMS WORKSPACE
# ==============================================================================

class MinisterialExamListView(ControlPermissionRequiredMixin, View):
    """
    Browser for ministerial exams with filtering, pagination, and status indicators.
    """
    permission_required = "ministerial_exams.view_ministerialexam"

    def get(self, request):
        form = MinisterialExamFilterForm(request.GET)
        qs = MinisterialExam.objects.select_related("subject", "term").annotate(
            sections_count=Count("sections", distinct=True)
        ).order_by("-exam_year", "model_number", "id")

        if form.is_valid():
            if form.cleaned_data.get("subject"):
                qs = qs.filter(subject=form.cleaned_data["subject"])
            if form.cleaned_data.get("exam_year"):
                qs = qs.filter(exam_year=form.cleaned_data["exam_year"])
            if form.cleaned_data.get("exam_role"):
                qs = qs.filter(exam_role=form.cleaned_data["exam_role"])
            if form.cleaned_data.get("status"):
                qs = qs.filter(status=form.cleaned_data["status"])
            if form.cleaned_data.get("q"):
                query = form.cleaned_data["q"]
                qs = qs.filter(Q(title__icontains=query) | Q(model_code__icontains=query))

        paginator = Paginator(qs, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "form": form,
            "page_obj": page_obj,
            "exams": page_obj.object_list,
            "total_count": paginator.count,
            "active_tab": "ministerial",
        }

        if request.headers.get("HX-Request"):
            return render(request, "control/assessments/ministerial/partials/table.html", context)

        return render(request, "control/assessments/ministerial/list.html", context)


class MinisterialExamDetailView(ControlPermissionRequiredMixin, View):
    """
    Detail view of a Ministerial Exam showing sections, ordered items, totals,
    links to ADM-03 for question editing, and operational actions.
    """
    permission_required = "ministerial_exams.view_ministerialexam"

    def get(self, request, pk):
        exam = get_object_or_404(
            MinisterialExam.objects.select_related("subject", "term", "assessment"),
            pk=pk
        )
        sections = exam.sections.all().order_by("sort_order")
        items = exam.items.select_related(
            "section",
            "question_version__question__subject",
            "question_version__question__unit",
            "question_version__question__lesson",
        ).order_by("sort_order", "question_number")

        context = {
            "exam": exam,
            "sections": sections,
            "items": items,
            "reorder_form": MinisterialItemReorderForm(),
            "active_tab": "ministerial",
        }
        return render(request, "control/assessments/ministerial/detail.html", context)


class MinisterialExamValidateView(ControlPermissionRequiredMixin, View):
    """
    Validates ministerial exam publishability using authoritative service.
    """
    permission_required = "ministerial_exams.view_ministerialexam"

    def get(self, request, pk):
        exam = get_object_or_404(MinisterialExam, pk=pk)
        try:
            validate_ministerial_exam_publishability(exam)
            is_valid = True
            error_message = None
        except ValidationError as exc:
            is_valid = False
            error_message = exc.messages if hasattr(exc, "messages") else str(exc)

        context = {
            "exam": exam,
            "is_valid": is_valid,
            "error_message": error_message,
        }
        return render(request, "control/assessments/ministerial/partials/validate_result.html", context)


class MinisterialExamRecalculateView(ControlPermissionRequiredMixin, View):
    """
    Recalculates ministerial exam totals using authoritative service.
    """
    permission_required = "ministerial_exams.change_ministerialexam"

    def post(self, request, pk):
        exam = get_object_or_404(MinisterialExam, pk=pk)
        updated_exam = recalculate_exam_totals(exam)
        from apps.control.models import ControlAuditLog
        from apps.control.services.audit_service import record_control_action
        record_control_action(
            action=ControlAuditLog.ActionChoices.MINISTERIAL_SYNC,
            target_type="ministerial_exam",
            target_id=str(exam.id),
            target_repr=f"إعادة حساب مجاميع النموذج الوزاري {exam.title or exam.model_code}",
            metadata={"total_questions": updated_exam.total_questions, "total_points": float(updated_exam.total_points)},
            request=request,
        )
        messages.success(
            request,
            f"تمت إعادة حساب مجاميع النموذج الوزاري بنجاح: {updated_exam.total_questions} سؤال، {updated_exam.total_points} درجة."
        )
        return redirect("control:ministerial_detail", pk=exam.pk)


class MinisterialExamReorderView(ControlPermissionRequiredMixin, View):
    """
    Safely reorders ministerial exam items inside an atomic transaction.
    """
    permission_required = "ministerial_exams.change_ministerialexam"

    @transaction.atomic
    def post(self, request, pk):
        exam = get_object_or_404(MinisterialExam, pk=pk)
        form = MinisterialItemReorderForm(request.POST)
        if not form.is_valid():
            messages.error(request, "بيانات الترتيب غير صالحة.")
            return redirect("control:ministerial_detail", pk=exam.pk)

        items_data = form.cleaned_data["reorder_data"]
        # Temporary offset to avoid violating unique_exam_item_order during bulk reorder
        items_map = {str(item.id): item for item in exam.items.select_for_update()}

        offset = 10000
        for entry in items_data:
            item_id = str(entry.get("id"))
            if item_id in items_map:
                items_map[item_id].sort_order += offset
                items_map[item_id].question_number += offset
                items_map[item_id].save(update_fields=["sort_order", "question_number"])

        # Set actual final orders
        for entry in items_data:
            item_id = str(entry.get("id"))
            if item_id in items_map:
                new_order = int(entry.get("sort_order", 1))
                new_qnum = int(entry.get("question_number", new_order))
                items_map[item_id].sort_order = new_order
                items_map[item_id].question_number = new_qnum
                items_map[item_id].save(update_fields=["sort_order", "question_number"])

        recalculate_exam_totals(exam)
        messages.success(request, "تم حفظ الترتيب الجديد وإعادة حساب المجاميع بنجاح.")
        return redirect("control:ministerial_detail", pk=exam.pk)


class LessonMinisterialBatchesView(ControlPermissionRequiredMixin, View):
    """
    Workspace to inspect and synchronize lesson ministerial batches.
    """
    permission_required = "ministerial_exams.view_ministerialexam"

    def get(self, request):
        form = LessonBatchFilterForm(request.GET)
        selected_lesson = None
        batches = []
        ministerial_items_count = 0

        if form.is_valid() and form.cleaned_data.get("lesson"):
            selected_lesson = form.cleaned_data["lesson"]
            batches = LessonMinisterialBatch.objects.filter(lesson=selected_lesson).prefetch_related(
                "batch_items__ministerial_exam_item__ministerial_exam",
                "batch_items__ministerial_exam_item__question_version__question",
            ).order_by("batch_index")
            ministerial_items_count = MinisterialExamItem.objects.filter(
                question_version__question__lesson=selected_lesson,
                question_version__question__status=ContentStatus.PUBLISHED,
                ministerial_exam__status=ContentStatus.PUBLISHED,
            ).count()

        context = {
            "form": form,
            "selected_lesson": selected_lesson,
            "batches": batches,
            "ministerial_items_count": ministerial_items_count,
            "active_tab": "ministerial",
        }
        return render(request, "control/assessments/ministerial/batches.html", context)

    def post(self, request):
        lesson_id = request.POST.get("lesson_id")
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        batches = sync_lesson_ministerial_batches(lesson)
        messages.success(
            request,
            f"تمت مزامنة دفعات الدرس الوزارية بنجاح للدرس ({lesson.title}): إجمالي {len(batches)} دفعة."
        )
        return redirect(f"{reverse('control:ministerial_batches')}?lesson={lesson.id}&unit={lesson.unit_id}&subject={lesson.unit.subject_id}")


# ==============================================================================
# TRAINING BATCH WORKSPACE
# ==============================================================================

class TrainingBatchListView(ControlPermissionRequiredMixin, View):
    """
    Browser for training batches with scope filtering, pool health metrics, and sync.
    """
    permission_required = "assessments.view_trainingbatch"

    def get(self, request):
        form = TrainingBatchFilterForm(request.GET)
        qs = TrainingBatch.objects.select_related("subject", "unit", "lesson").annotate(
            actual_items_count=Count("items")
        ).order_by("scope_type", "scope_key", "batch_index")

        if form.is_valid():
            if form.cleaned_data.get("scope_type"):
                qs = qs.filter(scope_type=form.cleaned_data["scope_type"])
            if form.cleaned_data.get("subject"):
                qs = qs.filter(subject=form.cleaned_data["subject"])
            if form.cleaned_data.get("q"):
                query = form.cleaned_data["q"]
                qs = qs.filter(Q(scope_key__icontains=query) | Q(subject__name_ar__icontains=query))

        paginator = Paginator(qs, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "form": form,
            "page_obj": page_obj,
            "batches": page_obj.object_list,
            "total_count": paginator.count,
            "active_tab": "training",
        }

        if request.headers.get("HX-Request"):
            return render(request, "control/assessments/training/partials/table.html", context)

        return render(request, "control/assessments/training/list.html", context)


class TrainingBatchDetailView(ControlPermissionRequiredMixin, View):
    """
    Detail view of a Training Batch showing items, difficulty/type distributions, and links.
    """
    permission_required = "assessments.view_trainingbatch"

    def get(self, request, pk):
        batch = get_object_or_404(
            TrainingBatch.objects.select_related("subject", "unit", "lesson"),
            pk=pk
        )
        items = batch.items.select_related(
            "question_version__question__subject",
            "question_version__question__unit",
            "question_version__question__lesson",
        ).order_by("sort_order")

        # Distribution metrics
        difficulty_counts = {}
        type_counts = {}
        for item in items:
            q = item.question_version.question
            difficulty_counts[q.difficulty] = difficulty_counts.get(q.difficulty, 0) + 1
            type_counts[q.question_type] = type_counts.get(q.question_type, 0) + 1

        context = {
            "batch": batch,
            "items": items,
            "difficulty_counts": difficulty_counts,
            "type_counts": type_counts,
            "active_tab": "training",
        }
        return render(request, "control/assessments/training/detail.html", context)


class TrainingBatchSyncView(ControlPermissionRequiredMixin, View):
    """
    Triggers official training batch synchronization for a given scope.
    """
    permission_required = "assessments.view_trainingbatch"

    def post(self, request):
        scope_type = request.POST.get("scope_type")
        source_id = request.POST.get("source_id")

        if scope_type not in TrainingBatchScope.values:
            messages.error(request, "نطاق التدريب غير صالح.")
            return redirect("control:training_list")

        try:
            batches = sync_training_batches(scope_type, source_id)
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.TRAINING_SYNC,
                target_type="training_batches",
                target_id=str(source_id or scope_type),
                target_repr=f"مزامنة دفعات التدريب للنطاق {scope_type}",
                metadata={"scope_type": scope_type, "source_id": str(source_id or ""), "batch_count": len(batches)},
                request=request,
            )
            messages.success(
                request,
                f"تمت مزامنة دفعات التدريب بنجاح ({scope_type}): إجمالي {len(batches)} دفعة في هذا النطاق."
            )
        except Exception as exc:
            messages.error(request, f"حدث خطأ أثناء مزامنة دفعات التدريب: {exc}")

        return redirect("control:training_list")


# ==============================================================================
# MOCK EXAM / BLUEPRINT WORKSPACE
# ==============================================================================

class MockBlueprintListView(ControlPermissionRequiredMixin, View):
    """
    Browser for AssessmentBlueprints and their versions.
    """
    permission_required = "assessments.view_assessmentblueprintversion"

    def get(self, request):
        form = MockBlueprintFilterForm(request.GET)
        qs = AssessmentBlueprint.objects.select_related("subject").prefetch_related(
            "versions"
        ).order_by("subject__sort_order", "title")

        if form.is_valid():
            if form.cleaned_data.get("subject"):
                qs = qs.filter(subject=form.cleaned_data["subject"])
            if form.cleaned_data.get("status"):
                qs = qs.filter(status=form.cleaned_data["status"])
            if form.cleaned_data.get("q"):
                query = form.cleaned_data["q"]
                qs = qs.filter(Q(title__icontains=query) | Q(key__icontains=query))

        paginator = Paginator(qs, 15)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "form": form,
            "page_obj": page_obj,
            "blueprints": page_obj.object_list,
            "total_count": paginator.count,
            "active_tab": "mock",
        }
        return render(request, "control/assessments/mock/list.html", context)


class MockBlueprintVersionDetailView(ControlPermissionRequiredMixin, View):
    """
    Detailed inspection of an AssessmentBlueprintVersion.
    Draft versions can be edited; Published versions are strictly immutable.
    Readiness report is displayed via blueprint_pool_readiness.
    """
    permission_required = "assessments.view_assessmentblueprintversion"

    def get(self, request, blueprint_id, version_id):
        blueprint = get_object_or_404(AssessmentBlueprint.objects.select_related("subject"), pk=blueprint_id)
        version = get_object_or_404(AssessmentBlueprintVersion, pk=version_id, blueprint=blueprint)

        readiness = blueprint_pool_readiness(version)
        form = MockBlueprintVersionDraftForm(instance=version)

        context = {
            "blueprint": blueprint,
            "version": version,
            "readiness": readiness,
            "form": form,
            "is_published": version.status == ContentStatus.PUBLISHED,
            "active_tab": "mock",
        }
        return render(request, "control/assessments/mock/version_detail.html", context)

    def post(self, request, blueprint_id, version_id):
        blueprint = get_object_or_404(AssessmentBlueprint.objects.select_related("subject"), pk=blueprint_id)
        version = get_object_or_404(AssessmentBlueprintVersion, pk=version_id, blueprint=blueprint)

        if version.status == ContentStatus.PUBLISHED:
            messages.error(request, "لا يمكن تعديل إصدار منشور؛ الإصدارات المنشورة محمية وغير قابلة للتعديل.")
            return redirect("control:mock_version_detail", blueprint_id=blueprint.pk, version_id=version.pk)

        form = MockBlueprintVersionDraftForm(request.POST, instance=version)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ تعديلات مسودة إصدار المخطط بنجاح.")
            return redirect("control:mock_version_detail", blueprint_id=blueprint.pk, version_id=version.pk)

        readiness = blueprint_pool_readiness(version)
        context = {
            "blueprint": blueprint,
            "version": version,
            "readiness": readiness,
            "form": form,
            "is_published": False,
            "active_tab": "mock",
        }
        return render(request, "control/assessments/mock/version_detail.html", context)


class MockBlueprintVersionPublishView(ControlPermissionRequiredMixin, View):
    """
    Publishes an AssessmentBlueprintVersion using the authoritative publish service.
    Strictly blocks publication if pool readiness is insufficient. Zero force publish!
    """
    permission_required = "assessments.change_assessmentblueprintversion"

    def post(self, request, blueprint_id, version_id):
        blueprint = get_object_or_404(AssessmentBlueprint, pk=blueprint_id)
        version = get_object_or_404(AssessmentBlueprintVersion, pk=version_id, blueprint=blueprint)

        try:
            publish_blueprint_version(version)
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.BLUEPRINT_PUBLISH,
                target_type="assessment_blueprint_version",
                target_id=str(version.id),
                target_repr=f"نشر مخطط المحاكاة {blueprint.title} (V{version.version_number})",
                metadata={"blueprint_id": str(blueprint.id), "version_number": version.version_number},
                request=request,
            )
            messages.success(request, f"تم نشر الإصدار {version.version_number} لمخطط المحاكاة بنجاح!")
        except (ApplicationError, ValidationError) as exc:
            msg = exc.message if hasattr(exc, "message") else str(exc)
            if hasattr(exc, "fields") and exc.fields:
                msg += f" - النقص: {json.dumps(exc.fields.get('missing_buckets', []), ensure_ascii=False)}"
            messages.error(request, f"تعذر النشر: {msg}")

        return redirect("control:mock_version_detail", blueprint_id=blueprint.pk, version_id=version.pk)


# ==============================================================================
# CUSTOM TEST DIAGNOSTICS & READINESS WORKSPACE
# ==============================================================================

class CustomTestReadinessView(ControlPermissionRequiredMixin, View):
    """
    Read-only diagnostics and pool availability monitor for Custom Tests.
    Inspects available published questions across subjects, units, difficulties, and types
    without modifying the selection engine or runtime settings.
    """
    permission_required = "assessments.view_assessment"

    def get(self, request):
        subjects = Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by("grade__sort_order", "sort_order")
        selected_subject_id = request.GET.get("subject_id")

        selected_subject = None
        pool_stats = {}
        units_stats = []

        if selected_subject_id:
            selected_subject = subjects.filter(id=selected_subject_id).first()

        if not selected_subject and subjects.exists():
            selected_subject = subjects.first()

        if selected_subject:
            # Training questions pool
            training_qs = QuestionVersion.objects.filter(
                question__subject=selected_subject,
                question__source_type=SourceType.TRAINING,
                question__status=ContentStatus.PUBLISHED,
                status=ContentStatus.PUBLISHED,
                question__current_version_id=F("id"),
            )
            # Ministerial questions pool
            ministerial_qs = MinisterialExamItem.objects.filter(
                question_version__question__subject=selected_subject,
                question_version__question__source_type=SourceType.MINISTERIAL,
                question_version__question__status=ContentStatus.PUBLISHED,
                question_version__status=ContentStatus.PUBLISHED,
                question_version__question__current_version_id=F("question_version_id"),
                ministerial_exam__status=ContentStatus.PUBLISHED,
            )

            total_training = training_qs.count()
            total_ministerial = ministerial_qs.count()

            # Breakdown by difficulty
            difficulties = {}
            for diff in DifficultyLevel.values:
                difficulties[diff] = {
                    "training": training_qs.filter(question__difficulty=diff).count(),
                    "ministerial": ministerial_qs.filter(question_version__question__difficulty=diff).count(),
                }

            # Breakdown by unit
            for unit in selected_subject.units.filter(status=ContentStatus.PUBLISHED).order_by("sort_order"):
                u_training = training_qs.filter(question__unit=unit).count()
                u_ministerial = ministerial_qs.filter(question_version__question__unit=unit).count()
                units_stats.append({
                    "unit": unit,
                    "training_count": u_training,
                    "ministerial_count": u_ministerial,
                    "total": u_training + u_ministerial,
                })

            pool_stats = {
                "total_training": total_training,
                "total_ministerial": total_ministerial,
                "total_available": total_training + total_ministerial,
                "difficulties": difficulties,
            }

        context = {
            "subjects": subjects,
            "selected_subject": selected_subject,
            "pool_stats": pool_stats,
            "units_stats": units_stats,
            "active_tab": "assessments",
        }
        return render(request, "control/assessments/custom_tests/readiness.html", context)
