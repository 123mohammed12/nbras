"""
AppConfig for apps.control.
"""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ControlConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.control"
    verbose_name = "منصة العمليات"

    def ready(self):
        # 1. Apply Super Admin boundary to Django Admin (/admin/)
        from apps.control.admin_boundary import apply_admin_boundary
        apply_admin_boundary()

        # 2. Connect post_migrate signal to idempotently provision Staff group
        def on_post_migrate(sender, **kwargs):
            if sender.name == self.name:
                from apps.control.services.bootstrap import ensure_staff_group
                try:
                    ensure_staff_group()
                except Exception as exc:
                    import logging
                    logging.getLogger("control.apps").warning(
                        "Post-migrate bootstrap of Staff group deferred: %s", exc
                    )

        post_migrate.connect(on_post_migrate, sender=self)
