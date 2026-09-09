import re
from decimal import Decimal


def normalize_text_for_grading(text: str | None) -> str:
    if not text:
        return ""
    # Strip, collapse whitespace, and casefold
    cleaned = re.sub(r"\s+", " ", text.strip()).casefold()
    # Remove Arabic Tatweel (Kashida)
    cleaned = cleaned.replace("ـ", "")
    # Normalize Eastern Arabic digits to ASCII digits
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    ascii_digits = "0123456789"
    digit_trans = str.maketrans(arabic_digits, ascii_digits)
    cleaned = cleaned.translate(digit_trans)
    # Normalize Alif Hamza variations to bare Alif (safe normalization)
    cleaned = cleaned.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    return cleaned



def grade_attempt_answer(
    *,
    question_snapshot: dict,
    answer_payload: dict,
    max_points: Decimal,
) -> dict:
    """
    Evaluates an answer purely using question_snapshot and answer_payload.
    Independent of live Question Bank models.
    """
    q_type = question_snapshot.get("question_type", "multiple_choice")
    explanation = question_snapshot.get("explanation", "")
    correct_option_id = question_snapshot.get("correct_option_id")
    correct_option_ids = question_snapshot.get("correct_option_ids", [])
    if not correct_option_ids and correct_option_id:
        correct_option_ids = [correct_option_id]

    selected_option_id = answer_payload.get("selected_option_id")
    correct_option_key = question_snapshot.get("correct_option_key")
    correct_option_keys = question_snapshot.get("correct_option_keys", [])
    if not correct_option_keys and correct_option_key:
        correct_option_keys = [correct_option_key]
    selected_option_key = answer_payload.get("selected_option_key")
    selected_option_keys = answer_payload.get("selected_option_keys", [])
    if selected_option_key and not selected_option_keys:
        selected_option_keys = [str(selected_option_key)]
    selected_option_ids = answer_payload.get("selected_option_ids", [])
    if selected_option_id and not selected_option_ids:
        selected_option_ids = [str(selected_option_id)]

    text_ans = answer_payload.get("text", answer_payload.get("answer_text"))
    num_ans = answer_payload.get("value")

    # Result structure
    res = {
        "is_correct": False,
        "awarded_points": Decimal("0.00"),
        "feedback_state": "incorrect",
        "selected_option_id": str(selected_option_id) if selected_option_id else None,
        "selected_option_ids": [str(x) for x in selected_option_ids],
        "selected_option_key": str(selected_option_key) if selected_option_key else None,
        "selected_option_keys": [str(x) for x in selected_option_keys],
        "correct_option_id": str(correct_option_id) if correct_option_id else None,
        "correct_option_ids": [str(x) for x in correct_option_ids],
        "correct_option_key": str(correct_option_key) if correct_option_key else None,
        "correct_option_keys": [str(x) for x in correct_option_keys],
        "correct_answer": None,
        "explanation": explanation,
        "max_points": max_points,
    }

    # 1. Multiple Choice / True-False
    if q_type in ["multiple_choice", "true_false"]:
        if not selected_option_id and not selected_option_key:
            res["feedback_state"] = "unanswered"
            res["is_correct"] = False
            return res

        matches = (
            correct_option_key is not None
            and selected_option_key is not None
            and str(selected_option_key) == str(correct_option_key)
        ) or (
            correct_option_id is not None
            and selected_option_id is not None
            and str(selected_option_id) == str(correct_option_id)
        )
        if matches:
            res["is_correct"] = True
            res["awarded_points"] = max_points
            res["feedback_state"] = "correct"
        else:
            res["is_correct"] = False
            res["awarded_points"] = Decimal("0.00")
            res["feedback_state"] = "incorrect"
        return res

    # 2. Multiple Select
    if q_type == "multiple_select":
        if not selected_option_ids and not selected_option_keys:
            res["feedback_state"] = "unanswered"
            res["is_correct"] = False
            return res

        if selected_option_keys and correct_option_keys:
            set_student = set(str(x) for x in selected_option_keys)
            set_correct = set(str(x) for x in correct_option_keys)
        else:
            set_student = set(str(x) for x in selected_option_ids)
            set_correct = set(str(x) for x in correct_option_ids)

        if set_student == set_correct:
            res["is_correct"] = True
            res["awarded_points"] = max_points
            res["feedback_state"] = "correct"
        else:
            res["is_correct"] = False
            res["awarded_points"] = Decimal("0.00")
            res["feedback_state"] = "incorrect"
        return res

    # 3. Short Answer
    if q_type == "short_answer":
        if not text_ans:
            res["feedback_state"] = "unanswered"
            res["is_correct"] = False
            return res

        accepted = question_snapshot.get("accepted_answers", [])
        if not accepted:
            # Pending manual review if no canonical answers defined
            res["is_correct"] = None
            res["awarded_points"] = Decimal("0.00")
            res["feedback_state"] = "pending_manual_review"
            return res

        norm_student = normalize_text_for_grading(text_ans)
        norm_accepted = [normalize_text_for_grading(a) for a in accepted if a]

        if norm_student in norm_accepted:
            res["is_correct"] = True
            res["awarded_points"] = max_points
            res["feedback_state"] = "correct"
            res["correct_answer"] = accepted[0]
        else:
            res["is_correct"] = False
            res["awarded_points"] = Decimal("0.00")
            res["feedback_state"] = "incorrect"
            res["correct_answer"] = accepted[0]
        return res

    # 4. Numeric
    if q_type == "numeric":
        if num_ans is None and not text_ans:
            res["feedback_state"] = "unanswered"
            res["is_correct"] = False
            return res

        try:
            val_to_check = Decimal(str(num_ans if num_ans is not None else text_ans))
            expected = question_snapshot.get("expected_value")
            if expected is not None:
                exp_dec = Decimal(str(expected))
                tol = Decimal(str(question_snapshot.get("numeric_tolerance") or "0.00"))
                if abs(val_to_check - exp_dec) <= tol:
                    res["is_correct"] = True
                    res["awarded_points"] = max_points
                    res["feedback_state"] = "correct"
                    res["correct_answer"] = str(expected)
                else:
                    res["is_correct"] = False
                    res["awarded_points"] = Decimal("0.00")
                    res["feedback_state"] = "incorrect"
                    res["correct_answer"] = str(expected)
            else:
                res["is_correct"] = None
                res["awarded_points"] = Decimal("0.00")
                res["feedback_state"] = "pending_manual_review"
        except (ValueError, TypeError):
            res["is_correct"] = False
            res["awarded_points"] = Decimal("0.00")
            res["feedback_state"] = "incorrect"

        return res

    # 5. Essay
    if q_type == "essay":
        res["is_correct"] = None
        res["awarded_points"] = Decimal("0.00")
        res["feedback_state"] = "pending_manual_review" if text_ans else "unanswered"
        return res

    # Fallback
    res["is_correct"] = False
    res["awarded_points"] = Decimal("0.00")
    res["feedback_state"] = "incorrect"
    return res
