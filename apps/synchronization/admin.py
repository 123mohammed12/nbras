from django.contrib import admin
from apps.synchronization.models import SyncOperation, SyncBatchReceipt, SyncChange


@admin.register(SyncOperation)
class SyncOperationAdmin(admin.ModelAdmin):
    list_display = [
        "client_operation_id",
        "user",
        "installation",
        "operation_type",
        "status",
        "received_at",
        "processed_at",
    ]
    list_filter = ["status", "operation_type", "processing_version"]
    search_fields = [
        "client_operation_id",
        "idempotency_key",
        "user__phone",
        "user__public_code",
        "payload_hash",
    ]
    readonly_fields = [
        "id",
        "user",
        "study_enrollment",
        "installation",
        "client_operation_id",
        "idempotency_key",
        "operation_type",
        "entity_type",
        "entity_id",
        "normalized_payload",
        "payload_hash",
        "status",
        "response_status",
        "response_body",
        "error_code",
        "occurred_at",
        "received_at",
        "processed_at",
        "retry_count",
        "processing_version",
        "created_at",
        "updated_at",
    ]
    list_select_related = ["user", "installation", "study_enrollment"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(SyncBatchReceipt)
class SyncBatchReceiptAdmin(admin.ModelAdmin):
    list_display = [
        "client_batch_id",
        "user",
        "installation",
        "operations_count",
        "status",
        "received_at",
        "completed_at",
    ]
    list_filter = ["status"]
    search_fields = ["client_batch_id", "user__phone", "user__public_code", "payload_hash"]
    readonly_fields = [
        "id",
        "user",
        "study_enrollment",
        "installation",
        "client_batch_id",
        "payload_hash",
        "operations_count",
        "status",
        "response_body",
        "received_at",
        "completed_at",
        "created_at",
        "updated_at",
    ]
    list_select_related = ["user", "installation", "study_enrollment"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(SyncChange)
class SyncChangeAdmin(admin.ModelAdmin):
    list_display = [
        "sequence",
        "resource_type",
        "resource_id",
        "action",
        "resource_version",
        "changed_at",
    ]
    list_filter = ["action", "resource_type"]
    search_fields = ["resource_id", "resource_type"]
    readonly_fields = [
        "sequence",
        "resource_type",
        "resource_id",
        "action",
        "grade",
        "section",
        "subject",
        "unit",
        "lesson",
        "resource_version",
        "metadata_snapshot",
        "changed_at",
        "created_at",
    ]
    list_select_related = ["grade", "section", "subject", "unit", "lesson"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
