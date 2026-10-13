"""Net contents check: unit-aware comparison (750 mL == 75 cL == 0.75 L)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.checks.normalize import clean
from app.models import CheckResult, Status

ML_PER_UNIT = {
    "ml": 1.0,
    "cl": 10.0,
    "l": 1000.0,
    "floz": 29.5735,
    "gal": 3785.41,
}

_QTY = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*"
    r"(m\s?l|millilit(?:er|re)s?|c\s?l|centilit(?:er|re)s?|lit(?:er|re)s?|l|fl\.?\s*oz\.?|fluid\s+ounces?|oz\.?|gal(?:lons?)?\.?)"
    r"(?![a-z])",
    re.IGNORECASE,
)

RELATIVE_TOLERANCE = 0.01  # 1%: "12 fl oz" vs "355 mL" (354.9) should match


@dataclass(frozen=True)
class Quantity:
    amount: float
    unit: str        # canonical key from ML_PER_UNIT
    raw: str

    @property
    def ml(self) -> float:
        return self.amount * ML_PER_UNIT[self.unit]


def _unit_key(unit: str) -> str:
    u = re.sub(r"[\s.]", "", unit.lower())
    if u in ("ml",) or u.startswith("millilit"):
        return "ml"
    if u in ("cl",) or u.startswith("centilit"):
        return "cl"
    if u in ("l",) or u.startswith("lit"):
        return "l"
    if u.startswith("gal"):
        return "gal"
    return "floz"  # fl oz, oz, fluid ounce(s)


def find_quantities(text: str) -> list[Quantity]:
    out = []
    for m in _QTY.finditer(clean(text)):
        try:
            amount = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if amount > 0:
            out.append(Quantity(amount, _unit_key(m.group(2)), m.group(0).strip()))
    return out


def _same(a: Quantity, b: Quantity) -> bool:
    return abs(a.ml - b.ml) <= max(1.0, RELATIVE_TOLERANCE * b.ml)


def check_net_contents(expected: str, ocr_text: str) -> CheckResult:
    field, label = "net_contents", "Net contents"
    if not expected.strip():
        return CheckResult(field, label, Status.FAIL, "No net contents entered on the application.")

    exp = find_quantities(expected)
    if not exp:
        return CheckResult(field, label, Status.REVIEW,
                           "Couldn't understand the application value. Enter it like “750 mL”.",
                           expected=expected)
    target = exp[0]

    found = find_quantities(ocr_text)
    if not found:
        return CheckResult(field, label, Status.FAIL, "No net contents statement found on the label.",
                           expected=target.raw)

    exact_unit = [q for q in found if _same(q, target) and q.unit == target.unit]
    converted = [q for q in found if _same(q, target)]
    if exact_unit:
        return CheckResult(field, label, Status.PASS, "Matches.", expected=target.raw, found=exact_unit[0].raw)
    if converted:
        return CheckResult(field, label, Status.PASS, "Matches (same volume in different units).",
                           expected=target.raw, found=converted[0].raw,
                           details=[f"{converted[0].raw} ≈ {target.raw}"])

    shown = ", ".join(q.raw for q in found)
    return CheckResult(field, label, Status.FAIL, f"Label shows {shown}; application says {target.raw}.",
                       expected=target.raw, found=shown)
