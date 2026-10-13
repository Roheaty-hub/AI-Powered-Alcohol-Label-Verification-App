"""Orchestrates one label verification: preprocess -> OCR -> field checks -> report."""
from __future__ import annotations

import time

import numpy as np

from app.checks.alcohol import check_alcohol
from app.checks.net_contents import check_net_contents
from app.checks.text_fields import check_text_field
from app.checks.warning import check_warning
from app.models import ApplicationData, OcrResult, Status, VerificationReport
from app.pipeline import preprocess
from app.pipeline.ocr import Extractor, TesseractExtractor, score

# If the first OCR pass looks weak, try a second preprocessing variant —
# but only while we're comfortably inside the ~5 second budget.
RETRY_BELOW_CONFIDENCE = 78
RETRY_TIME_BUDGET_MS = 2500

_default_extractor = TesseractExtractor()


def _run_ocr(image_bytes: bytes, extractor: Extractor) -> tuple[OcrResult, np.ndarray, float]:
    start = time.perf_counter()
    gray, angle = preprocess.base_gray(image_bytes)

    best = extractor.extract(preprocess.variant_contrast(gray), "contrast")

    elapsed_ms = (time.perf_counter() - start) * 1000
    if best.mean_confidence < RETRY_BELOW_CONFIDENCE and elapsed_ms < RETRY_TIME_BUDGET_MS:
        img_b = preprocess.variant_threshold(gray)
        alt = extractor.extract(img_b, "glare-correction")
        if score(alt) > score(best):
            best = alt
    # All variants share geometry with `gray`, so OCR boxes index into it directly.
    # The untouched grayscale is the most faithful source for measuring stroke weight.
    return best, gray, angle


def _image_quality(ocr: OcrResult, angle: float) -> tuple[str, str]:
    notes = []
    if abs(angle) >= 1:
        notes.append(f"straightened a {abs(angle):.1f}° tilt")
    if ocr.variant != "contrast":
        notes.append("applied glare/shadow correction")
    suffix = f" (Auto-{', '.join(notes)}.)" if notes else ""

    if ocr.word_count < 15 or ocr.mean_confidence < 55:
        return "poor", ("The label was hard to read. Results may be unreliable — "
                        "consider requesting a clearer image." + suffix)
    if ocr.mean_confidence < 75:
        return "fair", "Some text was hard to read; double-check flagged items." + suffix
    return "good", "Label text read clearly." + suffix


def verify_label(image_bytes: bytes, app: ApplicationData, extractor: Extractor | None = None) -> VerificationReport:
    start = time.perf_counter()
    ocr, gray, angle = _run_ocr(image_bytes, extractor or _default_extractor)
    text = ocr.text

    checks = [
        check_text_field("brand_name", "Brand name", app.brand_name, text),
        check_text_field("class_type", "Class / type", app.class_type, text),
        check_alcohol(app.alcohol_content, text, app.beverage_type),
        check_net_contents(app.net_contents, text),
        check_text_field("bottler", "Bottler / producer", app.bottler, text,
                         required=False, review_threshold=0.75),
        check_text_field("country_of_origin", "Country of origin", app.country_of_origin, text,
                         required=False),
        check_warning(ocr, gray),
    ]

    overall = Status.worst([c.status for c in checks])
    quality, quality_note = _image_quality(ocr, angle)
    if quality == "poor" and overall is Status.PASS:
        overall = Status.REVIEW

    n_fail = sum(c.status is Status.FAIL for c in checks)
    n_review = sum(c.status is Status.REVIEW for c in checks)
    summary = {
        Status.PASS: "Everything on the label matches the application.",
        Status.REVIEW: f"Looks good, but {n_review} item{'s' if n_review != 1 else ''} need{'s' if n_review == 1 else ''} a quick look.",
        Status.FAIL: f"{n_fail} item{'s' if n_fail != 1 else ''} do{'es' if n_fail == 1 else ''} not match.",
        Status.SKIPPED: "Nothing to check.",
    }[overall]

    return VerificationReport(
        overall=overall,
        summary=summary,
        checks=checks,
        image_quality=quality,
        image_quality_note=quality_note,
        ocr_text=text,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
    )
