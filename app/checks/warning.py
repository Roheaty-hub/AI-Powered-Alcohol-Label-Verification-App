"""Government Health Warning Statement check (27 CFR Part 16).

Three sub-checks, reported together:
  1. Header "GOVERNMENT WARNING:" is present and in ALL CAPS (case-sensitive).
  2. The statement body matches the statutory text word-for-word.
  3. The header appears bold (image heuristic; advisory only, never auto-fails).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from app.checks.normalize import clean, similarity, tokens
from app.models import CheckResult, OcrResult, OcrWord, Status

HEADER = "GOVERNMENT WARNING:"
BODY = (
    "(1) According to the Surgeon General, women should not drink alcoholic beverages during "
    "pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages "
    "impairs your ability to drive a car or operate machinery, and may cause health problems."
)
FULL_TEXT = f"{HEADER} {BODY}"

_HEADER_RE = re.compile(r"g\s*o\s*v\s*e\s*r\s*n\s*m\s*e\s*n\s*t\s*w\s*a\s*r\s*n\s*i\s*n\s*g\s*([:;.]?)", re.IGNORECASE)

# Body word-level similarity needed to call it "OCR noise" rather than a wording change.
BODY_REVIEW_RATIO = 0.93
WORD_NOISE_SIMILARITY = 0.7

# Header stroke width / body stroke width. Bold fonts measure ~1.3-1.5x on clean
# images; blur compresses the ratio toward 1.0, so the middle band is "can't tell".
BOLD_RATIO_PASS = 1.2
BOLD_RATIO_LIKELY_REGULAR = 1.05


def _find_header(text: str) -> re.Match | None:
    return _HEADER_RE.search(clean(text))


def _body_diff(found_tokens: list[str]) -> tuple[float, list[str], bool]:
    """Compare body tokens. Returns (ratio, human-readable differences, only_ocr_noise)."""
    expected = tokens(BODY)
    sm = SequenceMatcher(None, expected, found_tokens, autojunk=False)
    opcodes = sm.get_opcodes()
    # Ignore trailing label text that follows the warning (an "insert" at the very end).
    if opcodes and opcodes[-1][0] == "insert" and opcodes[-1][1] == len(expected):
        found_tokens = found_tokens[: opcodes[-1][3]]
        sm = SequenceMatcher(None, expected, found_tokens, autojunk=False)
        opcodes = sm.get_opcodes()

    diffs: list[str] = []
    noise_only = True
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        exp_words = " ".join(expected[i1:i2])
        got_words = " ".join(found_tokens[j1:j2])
        if tag == "replace":
            diffs.append(f"expected “{exp_words}”, label reads “{got_words}”")
            if (i2 - i1) != (j2 - j1) or similarity(exp_words, got_words) < WORD_NOISE_SIMILARITY:
                noise_only = False
        elif tag == "delete":
            diffs.append(f"missing “{exp_words}”")
            noise_only = False
        elif tag == "insert":
            diffs.append(f"extra words “{got_words}”")
            noise_only = False
    return sm.ratio(), diffs, noise_only


def _stroke_width(gray: np.ndarray, w: OcrWord) -> float | None:
    """Median stroke thickness (px) of the ink inside a word's bounding box."""
    x0, y0 = max(0, w.left), max(0, w.top)
    crop = gray[y0:y0 + w.height, x0:x0 + w.width]
    if crop.size == 0 or min(crop.shape) < 4:
        return None
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if ink.mean() > 127:  # light text on dark background
        ink = 255 - ink
    # For a thin stroke of width w and length L: area ≈ w·L and perimeter ≈ 2L,
    # so w ≈ 2·area / perimeter. Continuous and robust to letter shape.
    contours, _ = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    perimeter = sum(cv2.arcLength(c, True) for c in contours)
    area = float(np.count_nonzero(ink))
    return 2 * area / perimeter if perimeter > 0 else None


def _bold_ratio(ocr: OcrResult, gray: np.ndarray | None) -> float | None:
    if gray is None:
        return None
    header_words = [w for w in ocr.words if canonical_word(w.text) in ("government", "warning")]
    if not header_words:
        return None
    header_line = header_words[0].line_key
    # Body sample: words from the warning statement that are NOT the header.
    body_vocab = set(tokens(BODY)) - {"government", "warning"}
    body_words = [w for w in ocr.words
                  if canonical_word(w.text) in body_vocab and len(canonical_word(w.text)) >= 4 and w.conf > 50]
    if len(body_words) < 3:
        return None
    hs = [s for s in (_stroke_width(gray, w) for w in header_words if w.line_key == header_line) if s]
    bs = [s for s in (_stroke_width(gray, w) for w in body_words[:20]) if s]
    if not hs or not bs:
        return None
    return float(np.median(hs) / np.median(bs))


def canonical_word(text: str) -> str:
    t = tokens(text)
    return t[0] if t else ""


def check_warning(ocr: OcrResult, gray: np.ndarray | None = None) -> CheckResult:
    field, label = "government_warning", "Government warning"
    text = clean(ocr.text)
    statuses: list[Status] = []
    details: list[str] = []

    m = _find_header(text)
    if not m:
        # Maybe the whole statement is there but the header is mangled; check body alone.
        body_present = similarity(" ".join(tokens(BODY)), " ".join(tokens(text))) > 0.4
        msg = ("Warning text found, but the “GOVERNMENT WARNING:” heading is missing or unreadable."
               if body_present else "Government warning statement not found on the label.")
        return CheckResult(field, label, Status.FAIL, msg, expected=FULL_TEXT)

    header_raw = m.group(0)
    letters = re.sub(r"[^A-Za-z]", "", header_raw)
    found_header = header_raw.strip()

    # 1. Header capitalization
    if letters != letters.upper():
        statuses.append(Status.FAIL)
        details.append(f"Heading must be ALL CAPS — label shows “{found_header}”.")
    elif not m.group(1):
        statuses.append(Status.REVIEW)
        details.append("Heading is all caps, but the colon after “WARNING” wasn't detected.")
    elif m.group(1) != ":":
        statuses.append(Status.REVIEW)
        details.append(f"Heading punctuation reads “{m.group(1)}” — should be a colon (may be a misread).")
    else:
        statuses.append(Status.PASS)
        details.append("Heading “GOVERNMENT WARNING:” is in all caps.")

    # 2. Body wording
    after = text[m.end():]
    found_tokens = tokens(after)[: len(tokens(BODY)) + 25]
    ratio, diffs, noise_only = _body_diff(found_tokens)
    if not diffs:
        statuses.append(Status.PASS)
        details.append("Statement wording matches the required text exactly.")
    elif ratio >= BODY_REVIEW_RATIO and noise_only:
        statuses.append(Status.REVIEW)
        details.append(f"Wording is {ratio:.0%} identical; differences look like scanner misreads: "
                       + "; ".join(diffs[:4]) + ".")
    else:
        statuses.append(Status.FAIL)
        details.append("Wording differs from the required text: " + "; ".join(diffs[:5]) + ".")

    # 3. Bold heading (advisory)
    ratio_bold = _bold_ratio(ocr, gray)
    if ratio_bold is None:
        statuses.append(Status.REVIEW)
        details.append("Couldn't measure whether the heading is bold — please check visually.")
    elif ratio_bold >= BOLD_RATIO_PASS:
        statuses.append(Status.PASS)
        details.append("Heading appears bold.")
    elif ratio_bold < BOLD_RATIO_LIKELY_REGULAR:
        statuses.append(Status.REVIEW)
        details.append(f"Heading may not be bold (stroke weight {ratio_bold:.2f}× body text) — please check visually.")
    else:
        statuses.append(Status.REVIEW)
        details.append("Couldn't confirm the heading is bold (image too soft to measure reliably) — please check visually.")

    status = Status.worst(statuses)
    message = {
        Status.PASS: "Present, all caps, and worded correctly.",
        Status.REVIEW: "Present — a detail needs your eyes.",
        Status.FAIL: "Does not meet the warning requirements.",
    }[status]
    return CheckResult(field, label, status, message, expected=FULL_TEXT,
                       found=f"{found_header} " + " ".join(after.split()[:12]) + " …", details=details)
