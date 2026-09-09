import re
from datetime import datetime


def convert_arabic_digits(text: str) -> str:
    """
    Converts Eastern Arabic numerals (٠١٢٣٤٥٦٧٨٩) to Western digits (0123456789).
    """
    if not text:
        return text
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"
    translation_table = str.maketrans(arabic_digits, english_digits)
    return text.translate(translation_table)


def extract_last_gregorian_year(header: str) -> int:
    """
    Extracts the last valid Gregorian year from an exam title/header string.
    Example: '1446هـ 2024 2025م' -> 2025
    Example: 'العام الدراسي 2023 - 2024م' -> 2024
    """
    if not header:
        raise ValueError("رأس النموذج فارغ، متعذر استخراج السنة.")

    normalized_header = convert_arabic_digits(str(header))
    current_year = datetime.now().year

    # Match 4-digit numbers starting with 19 or 20
    matches = re.findall(r"(?:19|20)\d{2}", normalized_header)
    if not matches:
        raise ValueError(f"لم يتم العثور على سنة ميلادية صالحة في النص: '{header}'")

    gregorian_years = []
    for match_str in matches:
        year_val = int(match_str)
        # Verify range (e.g. 1900 to current_year + 2)
        if 1900 <= year_val <= (current_year + 2):
            gregorian_years.append(year_val)

    if not gregorian_years:
        raise ValueError(f"لم يتم العثور على سنة ميلادية ضمن النطاق المقبول في: '{header}'")

    return gregorian_years[-1]


def normalize_exam_role(role_raw: str) -> str | None:
    """
    Normalizes raw exam role string to canonical choice value:
    'first', 'second', 'supplementary', 'other', or None.
    """
    if not role_raw or str(role_raw).strip().lower() in ["none", "null", ""]:
        return None

    cleaned = str(role_raw).strip().lower()

    if any(kw in cleaned for kw in ["first", "أول", "الاول", "الأول"]):
        return "first"
    if any(kw in cleaned for kw in ["second", "ثاني", "الثاني"]):
        return "second"
    if any(kw in cleaned for kw in ["supplementary", "تكميلي", "التكميلي"]):
        return "supplementary"
    if any(kw in cleaned for kw in ["other", "آخر", "الآخر"]):
        return "other"

    return "other"
