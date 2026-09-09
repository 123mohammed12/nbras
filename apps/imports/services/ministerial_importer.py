"""Backward-compatible entry point for the shared content import pipeline."""

import json
from pathlib import Path

from apps.imports.services.content_importer import ContentBatchImporter, ImportSource
from apps.ministerial_exams.models import MinisterialExam


def import_ministerial_exam_json(*, file_path_or_dict: str | Path | dict) -> MinisterialExam:
    if isinstance(file_path_or_dict, (str, Path)):
        path = Path(file_path_or_dict)
        source = ImportSource(str(path), path.read_bytes())
        data = json.loads(source.content.decode("utf-8-sig"))
    else:
        data = file_path_or_dict
        source = ImportSource("inline-exam.json", json.dumps(data, ensure_ascii=False).encode("utf-8"))
    importer = ContentBatchImporter(
        [source], requested_type="exams", operation="upsert", enforce_quran_scope=False
    )
    importer.execute()
    return MinisterialExam.objects.get(model_code=data["exam_id"])
