from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_alter_phoneverification_purpose")]

    operations = [
        migrations.AddField(model_name="studentprofile", name="custom_governorate_name", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="studentprofile", name="custom_district_name", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="studentprofile", name="custom_isolation_name", field=models.CharField(blank=True, default="", max_length=100)),
    ]
