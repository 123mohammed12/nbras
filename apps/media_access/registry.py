from typing import Dict, Any, Optional
from django.apps import apps
from django.db.models import Model


class MediaResourceDefinition:
    def __init__(
        self,
        app_label: str,
        model_name: str,
        file_field_name: str,
        disposition: str = "attachment",
        allowed_mimes: Optional[list] = None,
    ):
        self.app_label = app_label
        self.model_name = model_name
        self.file_field_name = file_field_name
        self.disposition = disposition
        self.allowed_mimes = allowed_mimes or []

    def get_model(self) -> type[Model]:
        return apps.get_model(self.app_label, self.model_name)


class MediaResourceRegistry:
    _registry: Dict[str, MediaResourceDefinition] = {}

    @classmethod
    def register(cls, resource_type: str, definition: MediaResourceDefinition):
        cls._registry[resource_type] = definition

    @classmethod
    def get(cls, resource_type: str) -> Optional[MediaResourceDefinition]:
        return cls._registry.get(resource_type)

    @classmethod
    def is_valid_resource_type(cls, resource_type: str) -> bool:
        return resource_type in cls._registry


# Register closed allowed media resource types
MediaResourceRegistry.register(
    "summary_file",
    MediaResourceDefinition(
        app_label="content",
        model_name="Summary",
        file_field_name="file_path",
        disposition="attachment",
    ),
)

MediaResourceRegistry.register(
    "flashcard_front_image",
    MediaResourceDefinition(
        app_label="content",
        model_name="Flashcard",
        file_field_name="front_image_path",
        disposition="inline",
    ),
)

MediaResourceRegistry.register(
    "flashcard_back_image",
    MediaResourceDefinition(
        app_label="content",
        model_name="Flashcard",
        file_field_name="back_image_path",
        disposition="inline",
    ),
)

MediaResourceRegistry.register(
    "content_link_file",
    MediaResourceDefinition(
        app_label="content",
        model_name="ContentLink",
        file_field_name="attached_file_path",
        disposition="attachment",
    ),
)

MediaResourceRegistry.register(
    "content_link_thumbnail",
    MediaResourceDefinition(
        app_label="content",
        model_name="ContentLink",
        file_field_name="thumbnail_path",
        disposition="inline",
    ),
)

# ─── Question Bank & Ministerial Exams Resources ────────────
MediaResourceRegistry.register(
    "question_asset",
    MediaResourceDefinition(
        app_label="question_bank",
        model_name="QuestionAsset",
        file_field_name="file_path",
        disposition="inline",
    ),
)

MediaResourceRegistry.register(
    "question_option_image",
    MediaResourceDefinition(
        app_label="question_bank",
        model_name="QuestionOption",
        file_field_name="option_image_path",
        disposition="inline",
    ),
)

MediaResourceRegistry.register(
    "question_stimulus_image",
    MediaResourceDefinition(
        app_label="question_bank",
        model_name="QuestionStimulus",
        file_field_name="image_path",
        disposition="inline",
    ),
)

MediaResourceRegistry.register(
    "question_stimulus_file",
    MediaResourceDefinition(
        app_label="question_bank",
        model_name="QuestionStimulus",
        file_field_name="file_path",
        disposition="attachment",
    ),
)

MediaResourceRegistry.register(
    "ministerial_exam_source_file",
    MediaResourceDefinition(
        app_label="ministerial_exams",
        model_name="MinisterialExam",
        file_field_name="source_file_path",
        disposition="attachment",
    ),
)

MediaResourceRegistry.register(
    "ministerial_exam_item_source_image",
    MediaResourceDefinition(
        app_label="ministerial_exams",
        model_name="MinisterialExamItem",
        file_field_name="source_image_path",
        disposition="inline",
    ),
)

