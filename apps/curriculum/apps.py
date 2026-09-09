from django.apps import AppConfig


class CurriculumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.curriculum"
    verbose_name = "المناهج والدراسة"

    def ready(self):
        try:
            import apps.curriculum.services.merge_handler  # noqa: F401
        except Exception:
            pass
