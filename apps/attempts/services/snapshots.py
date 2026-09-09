from decimal import Decimal
from apps.question_bank.models import QuestionVersion, QuestionOption, QuestionStimulusLink, QuestionAsset


def build_attempt_question_snapshot(
    *,
    question_version: QuestionVersion,
    points: Decimal,
    options: list[QuestionOption] | None = None,
    source_metadata: dict | None = None,
) -> dict:
    """
    Builds a full, immutable JSON snapshot for an AttemptQuestion.
    Ensures attempt questions remain historical truth even if bank questions are edited later.
    """
    if options is None:
        options = list(QuestionOption.objects.filter(question_version=question_version).order_by("sort_order"))

    options_data = []
    correct_option_ids = []
    correct_option_keys = []
    correct_option_id = None
    correct_option_key = None

    for opt in options:
        opt_dict = {
            "id": str(opt.id),
            "option_key": opt.option_key,
            "option_text": opt.option_text or "",
            "option_image_path": opt.option_image_path.url if opt.option_image_path else None,
            "sort_order": opt.sort_order,
            "is_correct": opt.is_correct,
        }
        options_data.append(opt_dict)
        if opt.is_correct:
            correct_option_ids.append(str(opt.id))
            correct_option_keys.append(opt.option_key)
            if correct_option_id is None:
                correct_option_id = str(opt.id)
                correct_option_key = opt.option_key

    # Stimuli
    stimuli_data = []
    links = sorted(question_version.stimulus_links.all(), key=lambda item: item.sort_order)
    for link in links:
        stim = link.stimulus
        stimuli_data.append({
            "id": str(stim.id),
            "stimulus_type": stim.stimulus_type,
            "title": stim.title or "",
            "text_content": stim.text_content or "",
            "image_path": stim.image_path.url if stim.image_path else None,
            "file_path": stim.file_path.url if stim.file_path else None,
            "layout": getattr(stim, "layout", "text_only"),
        })

    q_obj = getattr(question_version, "question", None)
    q_type = q_obj.question_type if q_obj else "multiple_choice"
    source_type = q_obj.source_type if q_obj else "ministerial"
    difficulty = q_obj.difficulty if q_obj else "medium"

    snapshot = {
        "question_id": str(question_version.question_id) if q_obj else str(question_version.id),
        "question_version_id": str(question_version.id),
        "version_number": question_version.version_number,
        "question_type": q_type,
        "source_type": source_type,
        "difficulty": difficulty,
        "question_text": question_version.question_text or "",
        "prompt_layout": question_version.prompt_layout or "vertical",
        "points": float(points),
        "explanation": question_version.explanation or "",
        "model_answer": (question_version.answer_key or {}).get("model_answer")
        or (question_version.answer_key or {}).get("reference_answer")
        or (question_version.answer_key or {}).get("correct_answer"),
        "accepted_answers": getattr(question_version, "accepted_answers", []),
        "expected_value": getattr(question_version, "expected_value", None),
        "numeric_tolerance": getattr(question_version, "numeric_tolerance", None),
        "options": options_data,
        "correct_option_id": correct_option_id,
        "correct_option_ids": correct_option_ids,
        "correct_option_key": correct_option_key,
        "correct_option_keys": correct_option_keys,
        "stimuli": stimuli_data,
        "assets": [
            {
                "id": str(asset.id),
                "asset_type": asset.asset_type,
                "file_path": asset.file_path.url if asset.file_path else None,
                "alt_text": asset.alt_text or "",
                "caption": asset.caption or "",
                "sort_order": asset.sort_order,
            }
            for asset in sorted(
                question_version.assets.all(),
                key=lambda item: (item.sort_order, str(item.id)),
            )
        ],
        "source_metadata": source_metadata or {},
    }

    return snapshot
