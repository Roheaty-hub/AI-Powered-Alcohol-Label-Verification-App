"""Free-text field checks: brand name, class/type, bottler, country of origin."""
from __future__ import annotations

from app.checks.normalize import best_window_match, clean
from app.models import CheckResult, Status

# Similarity thresholds on normalized text (0..1).
PASS_THRESHOLD = 0.97    # effectively identical once case/punctuation are ignored
REVIEW_THRESHOLD = 0.82  # close enough that an OCR misread is the likely cause


def check_text_field(
    field: str,
    label: str,
    expected: str,
    ocr_text: str,
    *,
    required: bool = True,
    review_threshold: float = REVIEW_THRESHOLD,
) -> CheckResult:
    if not expected.strip():
        status = Status.FAIL if required else Status.SKIPPED
        msg = "No value entered on the application." if required else "Not provided — skipped."
        return CheckResult(field, label, status, msg)

    match = best_window_match(expected, ocr_text)
    if match is None:
        return CheckResult(field, label, Status.FAIL, "No readable text found on the label.", expected=expected)

    found = match.text
    if match.score >= PASS_THRESHOLD:
        exact = clean(found).strip() == clean(expected).strip()
        msg = "Matches." if exact else "Matches (differs only in capitalization or punctuation)."
        return CheckResult(field, label, Status.PASS, msg, expected=expected, found=found)

    if match.score >= review_threshold:
        return CheckResult(
            field, label, Status.REVIEW,
            "Close match — likely the same text, but please confirm.",
            expected=expected, found=found,
            details=[f"Similarity {match.score:.0%}. Small differences are often the scanner misreading a letter."],
        )

    found_text = found if match.score >= 0.5 else None
    msg = "Not found on the label." if found_text is None else "Does not match the label."
    return CheckResult(field, label, Status.FAIL, msg, expected=expected, found=found_text,
                       details=[f"Closest text on label: “{found}” ({match.score:.0%} similar)."]
                       if found_text else [])
