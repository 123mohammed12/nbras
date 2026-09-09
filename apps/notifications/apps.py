from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "الإشعارات"

    def ready(self):
        from apps.accounts.services.merge_service import register_merge_handler
        from .services import merge_notifications
        register_merge_handler(merge_notifications)
