from django.db import migrations


def remediate_legacy_operations(apps, schema_editor):
    SyncOperation = apps.get_model("synchronization", "SyncOperation")
    # Find operations with status='completed' that were created as part of the legacy stub
    legacy_ops = SyncOperation.objects.filter(status="completed", normalized_payload__isnull=True)
    count = legacy_ops.count()
    legacy_ops.update(
        status="failed",
        error_code="LEGACY_STUB_NOT_PROCESSED",
        processing_version="legacy_stub_v1",
    )
    print(f"Remediated {count} legacy stub sync operations to failed status.")


def reverse_remediation(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("synchronization", "0002_syncbatchreceipt_syncchange_and_more"),
    ]

    operations = [
        migrations.RunPython(remediate_legacy_operations, reverse_code=reverse_remediation),
    ]
