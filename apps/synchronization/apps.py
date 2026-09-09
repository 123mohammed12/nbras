from django.apps import AppConfig


class SynchronizationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.synchronization"
    verbose_name = "مزامنة البيانات والأوفلاين"

    def ready(self):
        try:
            import apps.synchronization.signals  # noqa
        except ImportError:
            pass

