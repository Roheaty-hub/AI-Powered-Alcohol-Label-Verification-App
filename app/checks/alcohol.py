"""Alcohol content check: compares ABV numerically and sanity-checks any proof statement."""
from __future__ import annotations

import re

from app.checks.normalize import clean
from app.models import BeverageType, CheckResult, Status

# OCR commonly confuses these characters with digits when they sit next to a "%".
_DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "S": "5", "s": "5", "I": "1", "l": "1", "|": "1"})

_PERCENT = re.compile(r"(?<![\w.])([0-9OoSsIl|]{1,2}(?:[.,][0-9OoSsIl|]{1,2})?)\s*%")
_PROOF = re.compile(r"(\d{2,3}(?:[.,]\d)?)\s*(?:°\s*)?proof", re.IGNORECASE)
_ALC_BY_VOL = re.compile(r"alc(?:ohol)?\.?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%?\s*(?:by\s*)?vol", re.IGNORECASE)

TOLERANCE = 0.05  # percentage points; treat 45 and 45.0 as equal, 45 vs 45.1 as different


def _to_float(s: str) -> float | None:
    try:
        return float(s.translate(_DIGIT_LOOKALIKES).replace(",", "."))
    except ValueError:
        return None


def parse_expected_abv(value: str) -> float | None:
    """Accepts '45', '45%', '45% Alc./Vol. (90 Proof)', or '90 Proof'."""
    value = clean(value)
    m = _PERCENT.search(value) or _ALC_BY_VOL.search(value)
    if m:
        return _to_float(m.group(1))
    m = _PROOF.search(value)
    if m:
        proof = _to_float(m.group(1))
        return proof / 2 if proof is not None else None
    m = re.fullmatch(r"\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*", value)
    return _to_float(m.group(1)) if m else None


def find_abv_values(ocr_text: str) -> list[float]:
    text = clean(ocr_text)
    values = [_to_float(m.group(1)) for m in _PERCENT.finditer(text)]
    values += [_to_float(m.group(1)) for m in _ALC_BY_VOL.finditer(text)]
    return sorted({v for v in values if v is not None and 0 < v <= 95})


def find_proof_values(ocr_text: str) -> list[float]:
    return sorted({v for v in (_to_float(m.group(1)) for m in _PROOF.finditer(clean(ocr_text))) if v})


def _fmt(v: float) -> str:
    return f"{v:g}%"


def check_alcohol(expected: str, ocr_text: str, beverage_type: BeverageType) -> CheckResult:
    field, label = "alcohol_content", "Alcohol content"
    optional = beverage_type in (BeverageType.WINE, BeverageType.BEER)

    if not expected.strip():
        if optional:
            return CheckResult(field, label, Status.SKIPPED,
                               "Not provided — alcohol content is optional for some wines and beers.")
        return CheckResult(field, label, Status.FAIL, "No alcohol content entered on the application.")

    exp = parse_expected_abv(expected)
    if exp is None:
        return CheckResult(field, label, Status.REVIEW,
                           "Couldn't understand the application value. Enter it like “45%”.",
                           expected=expected)

    found = find_abv_values(ocr_text)
    proofs = find_proof_values(ocr_text)

    if not found:
        return CheckResult(field, label, Status.FAIL, "No alcohol percentage found on the label.",
                           expected=_fmt(exp))

    matching = [v for v in found if abs(v - exp) <= TOLERANCE]
    if not matching:
        return CheckResult(field, label, Status.FAIL,
                           f"Label shows {', '.join(_fmt(v) for v in found)}; application says {_fmt(exp)}.",
                           expected=_fmt(exp), found=", ".join(_fmt(v) for v in found))

    details = []
    status = Status.PASS
    message = "Matches."
    if proofs:
        if any(abs(p - 2 * exp) <= 2 * TOLERANCE for p in proofs):
            details.append(f"Proof statement ({proofs[0]:g} proof) is consistent with {_fmt(exp)}.")
        else:
            status = Status.REVIEW
            message = "ABV matches, but the proof statement doesn't equal 2 × ABV."
            details.append(f"Label proof: {', '.join(f'{p:g}' for p in proofs)}; expected {2 * exp:g} proof.")
    if len(found) > 1:
        details.append(f"Multiple percentages on label: {', '.join(_fmt(v) for v in found)}.")

    return CheckResult(field, label, status, message, expected=_fmt(exp), found=_fmt(matching[0]), details=details)
