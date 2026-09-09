"""
Operational views for Question Bank Workspace in /control/.
Strictly orchestrates existing domain services and enums without inventing states or altering models.
"""

import json
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views import View
from django.views.generic import TemplateView

from apps.analytics.models import QuestionQualityAggregate
from apps.curriculum.models import ContentStatus, Lesson, Subject, Unit
from apps.control.forms.question_forms import (
    QuestionBulkActionForm,
    QuestionCreateForm,
    QuestionEditDraftForm,
    QuestionFilterForm,
)
from apps.control.permissions import ControlPermissionRequiredMixin
from apps.ministerial_exams.models import MinisterialExamItem
from apps.question_bank.health import (
    mock_blueprint_health,
    pool_health,
    training_batch_health,
)
from apps.question_bank.models import (
    DifficultyLevel,
    PromptLayout,
    Question,
    QuestionOption,
    QuestionType,
    QuestionVersion,
    SourceType,
)
from apps.question_bank.services import (
    approve_question_version,
    clone_question_version,
    publish_question_version,
    retire_question,
    send_question_version_to_review,
    validate_question_for_publication,
)


def _format_error(exc):
    if isinstance(exc, ValidationError):
        return "؛ ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
    return str(exc)


class QuestionListView(ControlPermissionRequiredMixin, View):
    """
    Main Question Bank operational workspace (/control/questions/).
    High-density, desktop-first, server-side pagination and active filter chips.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/list.html"

    def get(self, request):
        current_tab = request.GET.get("tab", "all")
        filter_form = QuestionFilterForm(request.GET)

        qs = (
            Question.objects.all()
            .select_related(
                "subject",
                "subject__grade",
                "subject__section",
                "unit",
                "lesson",
                "current_version",
                "created_by",
            )
            .prefetch_related(
                "current_version__ministerial_items__ministerial_exam",
                "current_version__quality_aggregates",
            )
            .order_by("-created_at")
        )

        # Tab filters based strictly on real domain states
        if current_tab == "draft":
            qs = qs.filter(status=ContentStatus.DRAFT)
        elif current_tab == "under_review":
            qs = qs.filter(status=ContentStatus.UNDER_REVIEW)
        elif current_tab == "approved":
            qs = qs.filter(status=ContentStatus.APPROVED)
        elif current_tab == "published":
            qs = qs.filter(status=ContentStatus.PUBLISHED)
        elif current_tab == "archived":
            qs = qs.filter(status=ContentStatus.ARCHIVED)
        elif current_tab == "needs_attention":
            # Questions with real quality flags or missing current_version
            flagged_version_ids = (
                QuestionQualityAggregate.objects.exclude(quality_flags=[])
                .values_list("question_version_id", flat=True)
            )
            qs = qs.filter(
                Q(current_version_id__in=flagged_version_ids)
                | Q(current_version__isnull=True)
            )

        # Apply search and form filters
        active_filters = []
        base_params = request.GET.copy()

        if filter_form.is_valid():
            data = filter_form.cleaned_data

            if data.get("q"):
                query_str = data["q"].strip()
                # Check for UUID prefix or exact ID
                if len(query_str) == 36 and "-" in query_str:
                    qs = qs.filter(Q(id=query_str) | Q(current_version_id=query_str))
                else:
                    qs = qs.filter(
                        Q(current_version__question_text__icontains=query_str)
                        | Q(id__startswith=query_str)
                    )
                p = base_params.copy()
                p.pop("q", None)
                active_filters.append({
                    "label": f'البحث: "{query_str}"',
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("subject"):
                subj = data["subject"]
                qs = qs.filter(subject=subj)
                p = base_params.copy()
                p.pop("subject", None)
                p.pop("unit", None)
                p.pop("lesson", None)
                active_filters.append({
                    "label": f"المادة: {subj.name_ar}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("unit"):
                unit_id = data["unit"]
                qs = qs.filter(unit_id=unit_id)
                u = Unit.objects.filter(id=unit_id).first()
                p = base_params.copy()
                p.pop("unit", None)
                p.pop("lesson", None)
                active_filters.append({
                    "label": f"الوحدة: {u.title if u else unit_id}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("lesson"):
                lesson_id = data["lesson"]
                qs = qs.filter(lesson_id=lesson_id)
                l = Lesson.objects.filter(id=lesson_id).first()
                p = base_params.copy()
                p.pop("lesson", None)
                active_filters.append({
                    "label": f"الدرس: {l.title if l else lesson_id}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("status"):
                st = data["status"]
                qs = qs.filter(status=st)
                p = base_params.copy()
                p.pop("status", None)
                active_filters.append({
                    "label": f"الحالة: {dict(ContentStatus.choices).get(st, st)}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("source_type"):
                src = data["source_type"]
                qs = qs.filter(source_type=src)
                p = base_params.copy()
                p.pop("source_type", None)
                active_filters.append({
                    "label": f"المصدر: {dict(SourceType.choices).get(src, src)}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("question_type"):
                qt = data["question_type"]
                qs = qs.filter(question_type=qt)
                p = base_params.copy()
                p.pop("question_type", None)
                active_filters.append({
                    "label": f"النوع: {dict(QuestionType.choices).get(qt, qt)}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("difficulty"):
                df = data["difficulty"]
                qs = qs.filter(difficulty=df)
                p = base_params.copy()
                p.pop("difficulty", None)
                active_filters.append({
                    "label": f"الصعوبة: {dict(DifficultyLevel.choices).get(df, df)}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("quality_flag"):
                qf = data["quality_flag"]
                qs = qs.filter(
                    current_version__quality_aggregates__quality_flags__contains=[qf]
                ).distinct()
                p = base_params.copy()
                p.pop("quality_flag", None)
                active_filters.append({
                    "label": f"إشارة: {qf}",
                    "remove_url": f"?{p.urlencode()}",
                })

            if data.get("year"):
                yr = data["year"]
                qs = qs.filter(
                    current_version__ministerial_items__ministerial_exam__exam_year=yr
                ).distinct()
                p = base_params.copy()
                p.pop("year", None)
                active_filters.append({
                    "label": f"السنة: {yr}",
                    "remove_url": f"?{p.urlencode()}",
                })

        # Calculate counts for tabs
        counts = {
            "all": Question.objects.count(),
            "draft": Question.objects.filter(status=ContentStatus.DRAFT).count(),
            "under_review": Question.objects.filter(status=ContentStatus.UNDER_REVIEW).count(),
            "approved": Question.objects.filter(status=ContentStatus.APPROVED).count(),
            "published": Question.objects.filter(status=ContentStatus.PUBLISHED).count(),
            "archived": Question.objects.filter(status=ContentStatus.ARCHIVED).count(),
        }

        # Server-side pagination
        page_number = request.GET.get("page", 1)
        paginator = Paginator(qs, 30)
        page_obj = paginator.get_page(page_number)

        # Build clean query string for pagination preserving all filters except page
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        pagination_querystring = pagination_params.urlencode()

        context = {
            "active_tab": "questions",
            "current_tab": current_tab,
            "filter_form": filter_form,
            "page_obj": page_obj,
            "total_count": paginator.count,
            "counts": counts,
            "active_filters": active_filters,
            "pagination_querystring": pagination_querystring,
        }

        if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
            return render(request, "control/questions/partials/question_table.html", context)

        return render(request, self.template_name, context)


class QuestionDetailView(ControlPermissionRequiredMixin, View):
    """
    Dedicated full Question detail operations page (/control/questions/<uuid:pk>/).
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/detail.html"

    def get(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related(
                "subject", "subject__grade", "subject__section",
                "unit", "lesson", "topic",
                "current_version",
                "created_by", "reviewed_by", "approved_by", "published_by"
            ),
            pk=pk,
        )

        current_version = question.current_version
        options = []
        assets = []
        stimuli = []
        validation_report = None
        ministerial_item = None
        quality_aggregate = None

        if current_version:
            options = list(current_version.options.order_by("sort_order", "option_key"))
            assets = list(current_version.assets.order_by("sort_order"))
            stimuli = [link.stimulus for link in current_version.stimulus_links.select_related("stimulus").order_by("sort_order")]
            validation_report = validate_question_for_publication(current_version)
            ministerial_item = current_version.ministerial_items.select_related(
                "ministerial_exam", "ministerial_exam__subject", "section"
            ).first()
            quality_aggregate = current_version.quality_aggregates.order_by("-sample_size").first()

        # If not on current version, check if another version has ministerial metadata
        if not ministerial_item and question.source_type == SourceType.MINISTERIAL:
            ministerial_item = MinisterialExamItem.objects.filter(
                question_version__question=question
            ).select_related("ministerial_exam", "section").first()

        versions = question.versions.select_related(
            "created_by", "reviewed_by", "approved_by", "published_by"
        ).order_by("-version_number")

        context = {
            "active_tab": "questions",
            "question": question,
            "version": current_version,
            "options": options,
            "assets": assets,
            "stimuli": stimuli,
            "validation_report": validation_report,
            "ministerial_item": ministerial_item,
            "quality_aggregate": quality_aggregate,
            "versions": versions,
        }
        return render(request, self.template_name, context)


class QuestionCreateView(ControlPermissionRequiredMixin, View):
    """
    Full-page authoring workspace to create a new Question and initial Draft version.
    """
    permission_required = "question_bank.add_question"
    template_name = "control/questions/editor.html"

    def get(self, request):
        initial = {}
        subject_id = request.GET.get("subject_id")
        unit_id = request.GET.get("unit_id")
        lesson_id = request.GET.get("lesson_id")
        if subject_id:
            initial["subject"] = subject_id
        if unit_id:
            initial["unit"] = unit_id
        if lesson_id:
            initial["lesson"] = lesson_id

        form = QuestionCreateForm(initial=initial)
        context = {
            "active_tab": "questions",
            "is_create": True,
            "form": form,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        form = QuestionCreateForm(request.POST)
        if form.is_valid():
            try:
                question = form.save(actor=request.user)
                messages.success(
                    request,
                    f"تم إنشاء السؤال الجديد بنجاح (المعرف: Q-{str(question.id)[:8]}). النسخة الأولى مسودة وقابلة للمراجعة.",
                )
                return redirect("control:question_detail", pk=question.pk)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, f"تعذر حفظ السؤال: {_format_error(exc)}")

        context = {
            "active_tab": "questions",
            "is_create": True,
            "form": form,
        }
        return render(request, self.template_name, context)


class QuestionEditView(ControlPermissionRequiredMixin, View):
    """
    Full-page authoring workspace to edit a Draft question version.
    HARD RULE: If published/frozen, editing in-place is blocked; cloning is prompted.
    """
    permission_required = "question_bank.change_question"
    template_name = "control/questions/editor.html"

    def get(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related("current_version", "subject", "unit", "lesson"),
            pk=pk,
        )
        version = question.current_version
        if not version:
            messages.error(request, "لا توجد نسخة حالية لهذا السؤال لتعديلها.")
            return redirect("control:question_detail", pk=question.pk)

        is_frozen = version.is_frozen
        form = QuestionEditDraftForm(version=version)

        context = {
            "active_tab": "questions",
            "is_create": False,
            "is_frozen": is_frozen,
            "question": question,
            "version": version,
            "form": form,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related("current_version"),
            pk=pk,
        )
        version = question.current_version
        if not version or version.is_frozen:
            messages.error(
                request,
                "النسخة الحالية منشورة ومحمية تاريخياً. يرجى إنشاء نسخة جديدة للتعديل.",
            )
            return redirect("control:question_detail", pk=question.pk)

        form = QuestionEditDraftForm(request.POST, version=version)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f"تم حفظ تعديلات النسخة (V{version.version_number}) بنجاح.")
                return redirect("control:question_detail", pk=question.pk)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, f"تعذر حفظ التعديلات: {_format_error(exc)}")

        context = {
            "active_tab": "questions",
            "is_create": False,
            "is_frozen": False,
            "question": question,
            "version": version,
            "form": form,
        }
        return render(request, self.template_name, context)


class QuestionCloneView(ControlPermissionRequiredMixin, View):
    """
    Safe cloning: clones a published version to create a new Draft version (e.g. V1 -> Draft V2).
    """
    permission_required = "question_bank.change_question"

    def post(self, request, pk):
        question = get_object_or_404(Question, pk=pk)
        try:
            clone = clone_question_version(question=question, actor=request.user)
            messages.success(
                request,
                f"تم إنشاء مسودة جديدة (النسخة V{clone.version_number}) بنجاح. النسخة السابقة تظل منشورة ونشطة حتى يتم اعتماد ونشر النسخة الجديدة.",
            )
            return redirect("control:question_detail", pk=question.pk)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, f"تعذر إنشاء نسخة جديدة: {_format_error(exc)}")
            return redirect("control:question_detail", pk=question.pk)


class QuestionStudentPreviewView(ControlPermissionRequiredMixin, View):
    """
    Semantic student preview: replicates student delivery without revealing correct answers.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/preview.html"

    def get(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related("current_version", "subject", "unit", "lesson"),
            pk=pk,
        )
        version = question.current_version
        options = version.options.order_by("sort_order", "option_key") if version else []
        assets = version.assets.order_by("sort_order") if version else []
        stimuli = [l.stimulus for l in version.stimulus_links.select_related("stimulus").order_by("sort_order")] if version else []

        context = {
            "active_tab": "questions",
            "question": question,
            "version": version,
            "options": options,
            "assets": assets,
            "stimuli": stimuli,
        }
        return render(request, self.template_name, context)


class QuestionReviewView(ControlPermissionRequiredMixin, View):
    """
    Dedicated Reviewer Workspace:
    Student-like preview side-by-side with answer key, explanation, points, and lifecycle buttons.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/review.html"

    def get(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related(
                "current_version", "subject", "unit", "lesson",
                "created_by", "reviewed_by", "approved_by", "published_by"
            ),
            pk=pk,
        )
        version = question.current_version
        options = version.options.order_by("sort_order", "option_key") if version else []
        assets = version.assets.order_by("sort_order") if version else []
        stimuli = [l.stimulus for l in version.stimulus_links.select_related("stimulus").order_by("sort_order")] if version else []
        validation_report = validate_question_for_publication(version) if version else None
        quality_aggregate = version.quality_aggregates.order_by("-sample_size").first() if version else None

        # Determine next allowed lifecycle action
        can_send_to_review = (
            version
            and version.status == ContentStatus.DRAFT
            and request.user.has_perm("question_bank.change_question")
        )
        can_approve = (
            version
            and version.status == ContentStatus.UNDER_REVIEW
            and request.user.has_perm("question_bank.review_question")
        )
        can_publish = (
            version
            and version.status == ContentStatus.APPROVED
            and request.user.has_perm("question_bank.publish_question")
        )
        can_retire = (
            question.status != ContentStatus.ARCHIVED
            and request.user.has_perm("question_bank.retire_question")
        )

        context = {
            "active_tab": "questions",
            "question": question,
            "version": version,
            "options": options,
            "assets": assets,
            "stimuli": stimuli,
            "validation_report": validation_report,
            "quality_aggregate": quality_aggregate,
            "can_send_to_review": can_send_to_review,
            "can_approve": can_approve,
            "can_publish": can_publish,
            "can_retire": can_retire,
        }
        return render(request, self.template_name, context)


class ReviewQueueView(ControlPermissionRequiredMixin, View):
    """
    Dedicated Review Queue to browse and process questions under review.
    """
    permission_required = "question_bank.review_question"
    template_name = "control/questions/review_queue.html"

    def get(self, request):
        pending_qs = (
            Question.objects.filter(status=ContentStatus.UNDER_REVIEW)
            .select_related("subject", "unit", "lesson", "current_version", "created_by")
            .order_by("updated_at")
        )

        subject_id = request.GET.get("subject")
        if subject_id:
            pending_qs = pending_qs.filter(subject_id=subject_id)

        paginator = Paginator(pending_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        subjects = Subject.objects.filter(
            questions__status=ContentStatus.UNDER_REVIEW
        ).distinct().order_by("name_ar")

        context = {
            "active_tab": "questions",
            "page_obj": page_obj,
            "total_pending": paginator.count,
            "subjects": subjects,
            "selected_subject": subject_id or "",
        }
        return render(request, self.template_name, context)


class QuestionValidateView(ControlPermissionRequiredMixin, View):
    """
    Runs authoritative backend validation and returns HTML report (or HTMX partial).
    """
    permission_required = "question_bank.view_question"

    def get(self, request, pk):
        question = get_object_or_404(Question.objects.select_related("current_version"), pk=pk)
        if not question.current_version:
            messages.error(request, "لا توجد نسخة حالية للتحقق منها.")
            return redirect("control:question_detail", pk=question.pk)

        report = validate_question_for_publication(question.current_version)

        if request.headers.get("HX-Request"):
            return render(
                request,
                "control/questions/partials/validation_report.html",
                {"validation_report": report, "question": question, "version": question.current_version},
            )

        if report["valid"]:
            messages.success(request, "السؤال مكتمل ومطابق لجميع معايير النشر التربوية والتقنية.")
        else:
            messages.warning(request, f"يحتوي السؤال على ملاحظات: {' | '.join(report['errors'])}")

        return redirect("control:question_detail", pk=question.pk)


class QuestionLifecycleActionView(ControlPermissionRequiredMixin, View):
    """
    Handles explicit lifecycle transitions (Send to Review, Approve, Publish, Retire).
    """
    def post(self, request, pk):
        question = get_object_or_404(
            Question.objects.select_related("current_version"),
            pk=pk,
        )
        version = question.current_version
        action = request.POST.get("action")

        if not version and action != "retire":
            messages.error(request, "لا توجد نسخة حالية للسؤال لتنفيذ الإجراء عليها.")
            return redirect("control:question_detail", pk=question.pk)

        try:
            if action == "send_to_review":
                send_question_version_to_review(version=version, actor=request.user)
                messages.success(request, f"تم إرسال النسخة (V{version.version_number}) إلى المراجعة والتدقيق.")

            elif action == "approve":
                approve_question_version(version=version, actor=request.user)
                from apps.control.models import ControlAuditLog
                from apps.control.services.audit_service import record_control_action
                record_control_action(
                    action=ControlAuditLog.ActionChoices.QUESTION_REVIEW,
                    target_type="question",
                    target_id=str(question.id),
                    target_repr=f"اعتماد النسخة V{version.version_number} للسؤال {str(question.id)[:8]}",
                    metadata={"version_number": version.version_number, "action": "approve"},
                    request=request,
                )
                messages.success(request, f"تم اعتماد النسخة (V{version.version_number}) بنجاح.")

            elif action == "publish":
                publish_question_version(version=version, actor=request.user)
                from apps.control.models import ControlAuditLog
                from apps.control.services.audit_service import record_control_action
                record_control_action(
                    action=ControlAuditLog.ActionChoices.QUESTION_PUBLISH,
                    target_type="question",
                    target_id=str(question.id),
                    target_repr=f"نشر النسخة V{version.version_number} للسؤال {str(question.id)[:8]}",
                    metadata={"version_number": version.version_number, "action": "publish"},
                    request=request,
                )
                messages.success(request, f"تم نشر النسخة (V{version.version_number}) للطلاب بنجاح وتجميد بياناتها.")

            elif action == "retire":
                retire_question(question=question, actor=request.user)
                from apps.control.models import ControlAuditLog
                from apps.control.services.audit_service import record_control_action
                record_control_action(
                    action=ControlAuditLog.ActionChoices.QUESTION_RETIRE,
                    target_type="question",
                    target_id=str(question.id),
                    target_repr=f"أرشفة/استبعاد السؤال {str(question.id)[:8]}",
                    metadata={"action": "retire"},
                    request=request,
                )
                messages.warning(request, "تمت أرشفة/تقاعد السؤال بنجاح وإيقاف ظهوره في الاختبارات الجديدة.")

            else:
                messages.error(request, "إجراء غير معروف.")

        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, f"فشل تنفيذ الإجراء: {_format_error(exc)}")

        return redirect("control:question_detail", pk=question.pk)


class QuestionHistoricalVersionView(ControlPermissionRequiredMixin, View):
    """
    Read-only view for historical frozen question versions.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/detail.html"

    def get(self, request, pk, version_number):
        question = get_object_or_404(
            Question.objects.select_related("subject", "unit", "lesson", "current_version"),
            pk=pk,
        )
        version = get_object_or_404(
            question.versions.select_related(
                "created_by", "reviewed_by", "approved_by", "published_by"
            ),
            version_number=version_number,
        )
        options = list(version.options.order_by("sort_order", "option_key"))
        assets = list(version.assets.order_by("sort_order"))
        stimuli = [l.stimulus for l in version.stimulus_links.select_related("stimulus").order_by("sort_order")]
        validation_report = validate_question_for_publication(version)
        quality_aggregate = version.quality_aggregates.order_by("-sample_size").first()

        context = {
            "active_tab": "questions",
            "question": question,
            "version": version,
            "is_historical": True,
            "options": options,
            "assets": assets,
            "stimuli": stimuli,
            "validation_report": validation_report,
            "quality_aggregate": quality_aggregate,
            "versions": question.versions.order_by("-version_number"),
        }
        return render(request, self.template_name, context)


class QuestionVersionCompareView(ControlPermissionRequiredMixin, View):
    """
    Lightweight version comparison comparing authoring fields between two versions.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/compare.html"

    def get(self, request, pk):
        question = get_object_or_404(Question, pk=pk)
        from_num = request.GET.get("from_v")
        to_num = request.GET.get("to_v")

        versions = list(question.versions.order_by("-version_number"))
        if len(versions) < 2:
            messages.info(request, "يتطلب المقارنة وجود نسختين على الأقل لهذا السؤال.")
            return redirect("control:question_detail", pk=question.pk)

        v1 = versions[1]
        v2 = versions[0]

        if from_num:
            v1 = next((v for v in versions if str(v.version_number) == str(from_num)), v1)
        if to_num:
            v2 = next((v for v in versions if str(v.version_number) == str(to_num)), v2)

        # Compute comparison differences
        diffs = {
            "question_text": {
                "changed": v1.question_text != v2.question_text,
                "from": v1.question_text,
                "to": v2.question_text,
            },
            "points": {
                "changed": v1.points != v2.points,
                "from": v1.points,
                "to": v2.points,
            },
            "prompt_layout": {
                "changed": v1.prompt_layout != v2.prompt_layout,
                "from": v1.get_prompt_layout_display(),
                "to": v2.get_prompt_layout_display(),
            },
            "short_explanation": {
                "changed": v1.short_explanation != v2.short_explanation,
                "from": v1.short_explanation,
                "to": v2.short_explanation,
            },
            "explanation": {
                "changed": v1.explanation != v2.explanation,
                "from": v1.explanation,
                "to": v2.explanation,
            },
            "answer_key": {
                "changed": v1.answer_key != v2.answer_key,
                "from": json.dumps(v1.answer_key, ensure_ascii=False),
                "to": json.dumps(v2.answer_key, ensure_ascii=False),
            },
        }

        # Compare options
        opts1 = {opt.option_key: opt.option_text for opt in v1.options.all()}
        opts2 = {opt.option_key: opt.option_text for opt in v2.options.all()}
        all_keys = sorted(set(opts1.keys()) | set(opts2.keys()))
        options_diff = []
        for k in all_keys:
            t1 = opts1.get(k, "")
            t2 = opts2.get(k, "")
            options_diff.append({
                "key": k,
                "from": t1,
                "to": t2,
                "changed": t1 != t2,
            })

        context = {
            "active_tab": "questions",
            "question": question,
            "v1": v1,
            "v2": v2,
            "versions": versions,
            "diffs": diffs,
            "options_diff": options_diff,
        }
        return render(request, self.template_name, context)


class QuestionHealthView(ControlPermissionRequiredMixin, View):
    """
    Question Bank Health Workspace (/control/questions/health/).
    Reuses pool_health, training_batch_health, mock_blueprint_health, and QuestionQualityAggregate.
    """
    permission_required = "question_bank.view_question"
    template_name = "control/questions/health.html"

    def get(self, request):
        subject_id = request.GET.get("subject_id") or None
        subjects = Subject.objects.all().order_by("sort_order", "name_ar")

        p_health = pool_health(subject_id=subject_id)
        t_health = training_batch_health(subject_id=subject_id)
        m_health = mock_blueprint_health(subject_id=subject_id)

        # Quality aggregate flags summary
        quality_qs = QuestionQualityAggregate.objects.exclude(quality_flags=[])
        if subject_id:
            quality_qs = quality_qs.filter(subject_id=subject_id)

        flag_counts = {}
        for row in quality_qs.values_list("quality_flags", flat=True):
            for flag in row:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1

        context = {
            "active_tab": "questions",
            "subjects": subjects,
            "selected_subject": subject_id or "",
            "pool": p_health,
            "training": t_health,
            "mock": m_health,
            "flag_counts": flag_counts,
        }
        return render(request, self.template_name, context)


class QuestionBulkActionView(ControlPermissionRequiredMixin, View):
    """
    Safe bulk operations handler with pre-execution validation summary.
    Never silently bypasses validation and never force-publishes.
    """
    def post(self, request):
        form = QuestionBulkActionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "بيانات الإجراء المجمع غير صالحة.")
            return redirect("control:question_list")

        action = form.cleaned_data["action"]
        ids = form.cleaned_data["selected_ids"]

        questions = list(
            Question.objects.filter(id__in=ids)
            .select_related("current_version")
        )

        ok, failed, reasons = 0, 0, []

        for q in questions:
            version = q.current_version
            if not version:
                failed += 1
                reasons.append(f"Q-{str(q.id)[:8]}: لا توجد نسخة حالية")
                continue

            try:
                if action == QuestionBulkActionForm.ACTION_VALIDATE:
                    report = validate_question_for_publication(version)
                    if report["valid"]:
                        ok += 1
                    else:
                        failed += 1
                        reasons.append(f"Q-{str(q.id)[:8]}: {report['errors'][0] if report['errors'] else 'غير صالح'}")

                elif action == QuestionBulkActionForm.ACTION_SEND_REVIEW:
                    if not request.user.has_perm("question_bank.change_question"):
                        raise PermissionDenied
                    send_question_version_to_review(version=version, actor=request.user)
                    ok += 1

                elif action == QuestionBulkActionForm.ACTION_APPROVE:
                    if not request.user.has_perm("question_bank.review_question"):
                        raise PermissionDenied
                    approve_question_version(version=version, actor=request.user)
                    ok += 1

                elif action == QuestionBulkActionForm.ACTION_PUBLISH:
                    if not request.user.has_perm("question_bank.publish_question"):
                        raise PermissionDenied
                    publish_question_version(version=version, actor=request.user)
                    ok += 1

            except (ValidationError, PermissionDenied) as exc:
                failed += 1
                reasons.append(f"Q-{str(q.id)[:8]}: {_format_error(exc)}")

        action_name = dict(QuestionBulkActionForm.ACTION_CHOICES).get(action, action)
        if failed == 0:
            messages.success(request, f"تم تنفيذ ({action_name}) بنجاح لجميع الأسئلة المحددة ({ok} سؤال).")
        else:
            sample_reasons = " | ".join(reasons[:5])
            messages.warning(
                request,
                f"اكتمل الإجراء المجمع: نجح {ok} سؤال، وفشل {failed} سؤال. (ملاحظات: {sample_reasons})",
            )

        return redirect("control:question_list")


class QuestionUnitsHtmxView(ControlPermissionRequiredMixin, View):
    """
    HTMX helper returning `<option>` tags for units belonging to a selected subject.
    """
    permission_required = "question_bank.view_question"

    def get(self, request):
        subject_id = request.GET.get("subject")
        for_form = request.GET.get("for_form")
        units = Unit.objects.filter(subject_id=subject_id).order_by("sort_order", "title") if subject_id else []

        options = ['<option value="">جميع الوحدات</option>' if not for_form else '<option value="">-- اختر الوحدة --</option>']
        for u in units:
            options.append(f'<option value="{u.id}">{escape(u.title)}</option>')

        return HttpResponse("\n".join(options))


class QuestionLessonsHtmxView(ControlPermissionRequiredMixin, View):
    """
    HTMX helper returning `<option>` tags for lessons belonging to a selected unit.
    """
    permission_required = "question_bank.view_question"

    def get(self, request):
        unit_id = request.GET.get("unit")
        for_form = request.GET.get("for_form")
        lessons = Lesson.objects.filter(unit_id=unit_id).order_by("sort_order", "title") if unit_id else []

        options = ['<option value="">جميع الدروس</option>' if not for_form else '<option value="">-- اختر الدرس --</option>']
        for l in lessons:
            options.append(f'<option value="{l.id}">{escape(l.title)}</option>')

        return HttpResponse("\n".join(options))
