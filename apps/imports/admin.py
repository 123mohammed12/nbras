import json
import uuid

from django.contrib import admin, messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.urls import path

from apps.imports.forms import ContentImportForm
from apps.imports.models import ContentImportLog, ImportStatus
from apps.imports.services.content_importer import ContentBatchImporter, ContentImportError, sources_from_uploads


@admin.register(ContentImportLog)
class ContentImportLogAdmin(admin.ModelAdmin):
    change_list_template = "admin/imports/contentimportlog/change_list.html"
    list_display = ["id", "content_type", "operation", "status", "created_by", "created_at"]
    list_filter = ["content_type", "operation", "status", "created_at"]
    search_fields = ["id", "source_names", "source_checksum"]
    readonly_fields = [
        "id", "content_type", "operation", "status", "source_names", "source_checksum",
        "report", "errors", "warnings", "created_by", "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [path("run/", self.admin_site.admin_view(self.import_view), name="imports_contentimportlog_run")] + super().get_urls()

    def import_view(self, request):
        report = None
        report_json = None
        confirm_token = None
        form = ContentImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and request.POST.get("confirm_token"):
            token = request.POST["confirm_token"]
            staged = cache.get(f"content-import:{token}")
            if not staged or staged.get("user_id") != request.user.pk:
                messages.error(request, "انتهت صلاحية المعاينة؛ أعد رفع الملفات.")
            else:
                try:
                    from apps.imports.services.content_importer import ImportSource
                    sources = [ImportSource(item["name"], item["content"]) for item in staged["sources"]]
                    importer = ContentBatchImporter(
                        sources,
                        requested_type=staged["content_type"],
                        operation=staged["operation"],
                    )
                    report = importer.execute()
                    status = ImportStatus.SUCCEEDED
                    messages.success(request, "اكتمل الاستيراد الذري بعد التأكيد.")
                    cache.delete(f"content-import:{token}")
                except (ContentImportError, ValidationError, OSError, ValueError) as exc:
                    error_list = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
                    report = {"errors": error_list, "failed": len(error_list)}
                    status = ImportStatus.FAILED
                    messages.error(request, "فشل التنفيذ؛ لم تُحفظ مجموعة بيانات جزئية.")
                ContentImportLog.objects.create(
                    content_type=report.get("content_type") or "mixed",
                    operation=staged["operation"], status=status,
                    source_names=[item["name"] for item in staged["sources"]],
                    source_checksum=staged["checksum"], report=report,
                    errors=report.get("errors", []), warnings=report.get("warnings", []),
                    created_by=request.user,
                )
                report_json = json.dumps(report, ensure_ascii=False, indent=2)
            form = ContentImportForm()
        elif request.method == "POST" and form.is_valid():
            source_names = [upload.name for upload in form.cleaned_data["files"]]
            operation = form.cleaned_data["operation"]
            try:
                sources = sources_from_uploads(form.cleaned_data["files"])
                importer = ContentBatchImporter(
                    sources,
                    requested_type=form.cleaned_data["content_type"],
                    operation=operation,
                )
                report = importer.preview()
                status = ImportStatus.PREVIEWED
                messages.success(request, "اكتملت المعاينة دون أي تغيير في البيانات.")
                checksum = importer.checksum
                if operation != "validate" and not report.get("errors"):
                    confirm_token = uuid.uuid4().hex
                    cache.set(
                        f"content-import:{confirm_token}",
                        {
                            "user_id": request.user.pk,
                            "content_type": form.cleaned_data["content_type"],
                            "operation": operation,
                            "checksum": checksum,
                            "sources": [{"name": item.name, "content": item.content} for item in sources],
                        },
                        timeout=900,
                    )
            except (ContentImportError, ValidationError, OSError, ValueError) as exc:
                error_list = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
                report = {"errors": error_list, "failed": len(error_list)}
                status = ImportStatus.FAILED
                checksum = ""
                messages.error(request, "فشل التحقق أو التنفيذ؛ لم تُحفظ أي تغييرات في المحتوى.")
            ContentImportLog.objects.create(
                content_type=(report.get("content_type") or (form.cleaned_data["content_type"] if form.cleaned_data["content_type"] != "auto" else "mixed")),
                operation=operation,
                status=status,
                source_names=source_names,
                source_checksum=checksum,
                report=report,
                errors=report.get("errors", []),
                warnings=report.get("warnings", []),
                created_by=request.user,
            )
            report_json = json.dumps(report, ensure_ascii=False, indent=2)
        context = {
            **self.admin_site.each_context(request),
            "title": "استيراد المحتوى التعليمي",
            "form": form,
            "report": report,
            "report_json": report_json,
            "confirm_token": confirm_token,
            "opts": self.model._meta,
        }
        return render(request, "admin/imports/contentimportlog/import_form.html", context)
