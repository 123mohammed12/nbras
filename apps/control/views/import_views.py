"""Import Center views for Operations Console (/control/imports/)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from apps.control.forms.import_forms import (
    ControlContentImportForm,
    ImportHistoryFilterForm,
    ReplaceScopeConfirmationForm,
)
from apps.control.services.import_runner import (
    execute_staged_import,
    get_staged_import,
    stage_import_preview,
)
from apps.imports.models import ContentImportLog, ImportStatus
from apps.imports.services.content_importer import (
    ContentBatchImporter,
    ContentImportError,
    sources_from_uploads,
)


class ImportBaseView(LoginRequiredMixin, View):
    """Base mixin enforcing Staff/Super Admin permission for Import Center."""

    active_tab = "imports"

    def has_view_permission(self) -> bool:
        user = self.request.user
        return (
            getattr(user, "is_superuser", False)
            or user.has_perm("imports.view_contentimportlog")
            or user.has_perm("imports.execute_import")
        )

    def has_execute_permission(self) -> bool:
        user = self.request.user
        return (
            getattr(user, "is_superuser", False)
            or user.has_perm("imports.execute_import")
        )

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/control/login/?next={request.path}")
        if not self.has_view_permission():
            raise PermissionDenied("ليس لديك الصلاحية الكافية للوصول إلى مركز الاستيراد.")
        return super().dispatch(request, *args, **kwargs)


class ImportOverviewView(ImportBaseView):
    """Import Center home workspace with recent operations, status metrics, and history."""

    template_name = "control/imports/overview.html"
    partial_template_name = "control/imports/partials/history_table.html"

    def get(self, request):
        now = timezone.now()
        day_ago = now - timedelta(hours=24)

        metrics = {
            "total_logs": ContentImportLog.objects.count(),
            "succeeded": ContentImportLog.objects.filter(status=ImportStatus.SUCCEEDED).count(),
            "failed": ContentImportLog.objects.filter(status=ImportStatus.FAILED).count(),
            "last_24h": ContentImportLog.objects.filter(created_at__gte=day_ago).count(),
        }

        form = ImportHistoryFilterForm(request.GET or None)
        qs = ContentImportLog.objects.select_related("created_by").order_by("-created_at")

        if form.is_valid():
            content_type = form.cleaned_data.get("content_type")
            operation = form.cleaned_data.get("operation")
            status = form.cleaned_data.get("status")
            q = form.cleaned_data.get("q")

            if content_type:
                qs = qs.filter(content_type=content_type)
            if operation:
                qs = qs.filter(operation=operation)
            if status:
                qs = qs.filter(status=status)
            if q:
                # Search by source names or checksum or ID
                if len(q) == 32 or len(q) == 36:
                    qs = qs.filter(id=q) if q.replace("-", "").isalnum() else qs.filter(source_checksum__icontains=q)
                else:
                    qs = qs.filter(source_names__icontains=q)

        paginator = Paginator(qs, 15)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": self.active_tab,
            "metrics": metrics,
            "filter_form": form,
            "page_obj": page_obj,
            "can_execute": self.has_execute_permission(),
        }

        if request.headers.get("HX-Request"):
            return render(request, self.partial_template_name, context)
        return render(request, self.template_name, context)


class ImportUploadView(ImportBaseView):
    """Step 1 & 2: Upload batch files, enforce security constraints, and run dry-run validation."""

    template_name = "control/imports/upload.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/control/login/?next={request.path}")
        if not self.has_execute_permission():
            raise PermissionDenied("يتطلب رفع وتنفيذ الاستيراد صلاحية imports.execute_import.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = ControlContentImportForm()
        return render(request, self.template_name, {
            "active_tab": self.active_tab,
            "form": form,
        })

    def post(self, request):
        form = ControlContentImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {
                "active_tab": self.active_tab,
                "form": form,
            })

        uploaded_files = form.cleaned_data["files"]
        content_type = form.cleaned_data["content_type"]
        operation = form.cleaned_data["operation"]
        source_names = [f.name for f in uploaded_files]

        try:
            sources = sources_from_uploads(uploaded_files)
            importer = ContentBatchImporter(
                sources,
                requested_type=content_type,
                operation=operation,
            )
            report = importer.preview()
            checksum = importer.checksum
            status = ImportStatus.PREVIEWED

            # Record preview log for complete audit traceability
            ContentImportLog.objects.create(
                content_type=report.get("content_type") or (content_type if content_type != "auto" else "mixed"),
                operation=operation,
                status=status,
                source_names=source_names,
                source_checksum=checksum,
                report=report,
                errors=report.get("errors", []),
                warnings=report.get("warnings", []),
                created_by=request.user,
            )

            if report.get("errors"):
                messages.error(request, "تم اكتشاف أخطاء تحقق تمنع التنفيذ. يرجى مراجعة التفاصيل وتصحيح الملفات.")
                return render(request, "control/imports/preview.html", {
                    "active_tab": self.active_tab,
                    "report": report,
                    "operation": operation,
                    "content_type": content_type,
                    "source_names": source_names,
                    "checksum": checksum,
                    "confirm_token": None,  # Blocked
                    "has_errors": True,
                })

            # Check if this was a validate-only operation
            if operation == "validate":
                messages.success(request, "اكتمل التحقق بنجاح دون أي أخطاء. لم يتم إجراء أي تعديل على قاعدة البيانات.")
                return render(request, "control/imports/preview.html", {
                    "active_tab": self.active_tab,
                    "report": report,
                    "operation": operation,
                    "content_type": content_type,
                    "source_names": source_names,
                    "checksum": checksum,
                    "confirm_token": None,
                    "is_validate_only": True,
                })

            # Valid batch for UPSERT or REPLACE_SCOPE -> Stage confirmation token
            confirm_token = stage_import_preview(
                user=request.user,
                sources=sources,
                content_type=content_type,
                operation=operation,
                checksum=checksum,
                report=report,
            )
            return redirect("control:import_preview", token=confirm_token)

        except (ContentImportError, ValidationError, OSError, ValueError) as exc:
            error_list = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
            report = {"errors": error_list, "failed": len(error_list)}
            ContentImportLog.objects.create(
                content_type=content_type if content_type != "auto" else "mixed",
                operation=operation,
                status=ImportStatus.FAILED,
                source_names=source_names,
                source_checksum="",
                report=report,
                errors=error_list,
                created_by=request.user,
            )
            messages.error(request, "تعذر قراءة الملفات أو التحقق من بنيتها.")
            return render(request, "control/imports/preview.html", {
                "active_tab": self.active_tab,
                "report": report,
                "operation": operation,
                "content_type": content_type,
                "source_names": source_names,
                "confirm_token": None,
                "has_errors": True,
            })


class ImportPreviewView(ImportBaseView):
    """Step 3: Dry-run forecast presentation, tabbed breakdown, and replace-scope confirmation."""

    template_name = "control/imports/preview.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/control/login/?next={request.path}")
        if not self.has_execute_permission():
            raise PermissionDenied("يتطلب فحص المعاينة وتأكيدها صلاحية imports.execute_import.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, token):
        staged = get_staged_import(token, request.user)
        if not staged:
            messages.error(request, "انتهت صلاحية المعاينة (المهلة 15 دقيقة)؛ يرجى إعادة رفع الملفات.")
            return redirect("control:import_upload")

        report = staged["report"]
        operation = staged["operation"]
        replace_scope_form = None
        if operation == "replace_scope":
            replace_scope_form = ReplaceScopeConfirmationForm(initial={"confirm_token": token})

        return render(request, self.template_name, {
            "active_tab": self.active_tab,
            "report": report,
            "operation": operation,
            "content_type": staged["content_type"],
            "source_names": [item["name"] for item in staged["sources"]],
            "checksum": staged.get("checksum", ""),
            "confirm_token": token,
            "replace_scope_form": replace_scope_form,
        })


class ImportConfirmView(ImportBaseView):
    """Step 4: Atomic execution of staged import batch with idempotency and double-submit protection."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/control/login/?next={request.path}")
        if not self.has_execute_permission():
            raise PermissionDenied("يتطلب تأكيد الاستيراد صلاحية imports.execute_import.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, token):
        staged = get_staged_import(token, request.user)
        if not staged:
            messages.error(request, "انتهت صلاحية المعاينة؛ يرجى إعادة رفع الملفات والتحقق منها.")
            return redirect("control:import_upload")

        replace_scope_confirmed = False
        if staged["operation"] == "replace_scope":
            form = ReplaceScopeConfirmationForm(request.POST)
            if not form.is_valid():
                messages.error(request, "يجب تحديد خانة الموافقة الصريحة لتأكيد استبدال النطاق.")
                return redirect("control:import_preview", token=token)
            replace_scope_confirmed = True

        try:
            log, report = execute_staged_import(
                token=token,
                user=request.user,
                replace_scope_confirmed=replace_scope_confirmed,
            )
            if log.status == ImportStatus.SUCCEEDED:
                from apps.control.models import ControlAuditLog
                from apps.control.services.audit_service import record_control_action
                record_control_action(
                    action=ControlAuditLog.ActionChoices.IMPORT_EXECUTE,
                    target_type="content_import_log",
                    target_id=str(log.id),
                    target_repr=f"استيراد {log.get_content_type_display()} ({log.get_operation_display()})",
                    metadata={
                        "content_type": log.content_type,
                        "operation": log.operation,
                        "source_count": len(log.source_names) if log.source_names else 0,
                    },
                    request=request,
                )
                messages.success(request, "اكتمل الاستيراد والتنفيذ الذري بنجاح.")
            else:
                messages.error(request, "فشل التنفيذ؛ تم التراجع الذري ولم تُحفظ أي بيانات جزئية.")
            return redirect("control:import_log_detail", id=log.id)

        except ContentImportError as exc:
            messages.error(request, str(exc))
            return redirect("control:import_preview", token=token)


class ImportLogDetailView(ImportBaseView):
    """Detailed audit view of a historical content import log."""

    template_name = "control/imports/log_detail.html"

    def get(self, request, id):
        log = get_object_or_404(ContentImportLog.objects.select_related("created_by"), pk=id)
        
        # Pretty-print report JSON safely for technical inspection
        report_json = ""
        if log.report:
            report_json = json.dumps(log.report, ensure_ascii=False, indent=2)

        return render(request, self.template_name, {
            "active_tab": self.active_tab,
            "log": log,
            "report_json": report_json,
        })
