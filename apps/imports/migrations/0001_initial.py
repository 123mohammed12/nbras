import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="ContentImportLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("content_type", models.CharField(choices=[("exams", "نماذج وزارية"), ("summaries", "ملخصات"), ("smart_cards", "بطاقات ذكية"), ("mixed", "دفعة مختلطة")], max_length=20)),
                ("operation", models.CharField(choices=[("validate", "تحقق ومعاينة"), ("upsert", "إضافة وتحديث"), ("replace_scope", "استبدال النطاق")], max_length=20)),
                ("status", models.CharField(choices=[("previewed", "تمت المعاينة"), ("succeeded", "نجح"), ("failed", "فشل")], db_index=True, max_length=20)),
                ("source_names", models.JSONField(blank=True, default=list)),
                ("source_checksum", models.CharField(blank=True, default="", max_length=64)),
                ("report", models.JSONField(blank=True, default=dict)),
                ("errors", models.JSONField(blank=True, default=list)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="content_import_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "سجل استيراد المحتوى", "verbose_name_plural": "سجلات استيراد المحتوى", "db_table": "content_import_logs", "ordering": ["-created_at"]},
        )
    ]
