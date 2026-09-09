from rest_framework import serializers
from apps.synchronization.models import SyncOperation, SyncBatchReceipt, SyncChange


class SyncOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncOperation
        fields = [
            "id",
            "client_operation_id",
            "idempotency_key",
            "operation_type",
            "entity_type",
            "entity_id",
            "status",
            "response_status",
            "response_body",
            "error_code",
            "processed_at",
            "created_at",
        ]


class SingleOperationItemSerializer(serializers.Serializer):
    client_operation_id = serializers.UUIDField(help_text="Unique client-generated operation ID.")
    operation_type = serializers.CharField(max_length=50, help_text="Type of operation.")
    resource_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    resource_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    client_event_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    client_session_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)


class SyncBatchRequestSerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=255, help_text="Unique client device installation ID.")
    client_batch_id = serializers.UUIDField(help_text="Unique client batch ID.")
    operations = serializers.ListField(
        child=serializers.JSONField(),
        help_text="List of operation payloads (max 50).",
    )


class OperationResultSerializer(serializers.Serializer):
    client_operation_id = serializers.CharField()
    status = serializers.CharField()
    response = serializers.JSONField(required=False)
    error = serializers.JSONField(required=False)


class BatchSummarySerializer(serializers.Serializer):
    completed = serializers.IntegerField()
    failed = serializers.IntegerField()
    conflict = serializers.IntegerField()


class SyncBatchResponseDataSerializer(serializers.Serializer):
    client_batch_id = serializers.CharField()
    results = OperationResultSerializer(many=True)
    summary = BatchSummarySerializer()


class SyncBatchResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = SyncBatchResponseDataSerializer()


class SyncManifestItemSerializer(serializers.Serializer):
    resource_type = serializers.CharField()
    resource_id = serializers.CharField()
    title = serializers.CharField()
    subject_id = serializers.CharField(allow_null=True)
    unit_id = serializers.CharField(allow_null=True)
    order = serializers.IntegerField()
    is_locked = serializers.BooleanField()
    is_free_preview = serializers.BooleanField()
    resource_version = serializers.CharField()
    updated_at = serializers.CharField(allow_null=True)
    download_available = serializers.BooleanField()
    protected_resource_type = serializers.CharField(allow_null=True)
    protected_resource_id = serializers.CharField(allow_null=True)


class SyncTombstoneSerializer(serializers.Serializer):
    resource_type = serializers.CharField()
    resource_id = serializers.CharField()
    action = serializers.CharField()
    sequence = serializers.IntegerField()
    occurred_at = serializers.CharField()


class SyncManifestResponseDataSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    mode = serializers.CharField()
    cursor = serializers.CharField()
    next_page_cursor = serializers.CharField(allow_null=True, required=False)
    access_revision = serializers.CharField()
    reset_required = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_null=True)
    items = SyncManifestItemSerializer(many=True)
    tombstones = SyncTombstoneSerializer(many=True)


class SyncManifestResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = SyncManifestResponseDataSerializer()
