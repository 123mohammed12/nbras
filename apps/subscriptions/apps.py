from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subscriptions"
    verbose_name = "الاشتراكات وأكواد التفعيل"

    def ready(self):
        try:
            import apps.subscriptions.services.merge_handler  # noqa: F401
        except ImportError:
            pass
