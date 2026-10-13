"""Core data types shared across the verification pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class Status(str, Enum):
    """Outcome of a single check. Ordered from best to worst."""

    PASS = "pass"        # Label matches the application.
    REVIEW = "review"    # Probably fine, but a human should glance at it.
    FAIL = "fail"        # Clear mismatch or missing element.
    SKIPPED = "skipped"  # Nothing to compare (field left blank / not required).

    @property
    def severity(self) -> int:
        return {Status.SKIPPED: 0, Status.PASS: 1, Status.REVIEW: 2, Status.FAIL: 3}[self]

    @staticmethod
    def worst(statuses: list["Status"]) -> "Status":
        relevant = [s for s in statuses if s is not Status.SKIPPED]
        if not relevant:
            return Status.SKIPPED
        return max(relevant, key=lambda s: s.severity)


class BeverageType(str, Enum):
    SPIRITS = "spirits"
    WINE = "wine"
    BEER = "beer"


@dataclass
class ApplicationData:
    """What the applicant claimed on the COLA application form."""

    brand_name: str = ""
    class_type: str = ""
    alcohol_content: str = ""
    net_contents: str = ""
    bottler: str = ""             # Name and address of bottler/producer (optional)
    country_of_origin: str = ""   # Imports only (optional)
    beverage_type: BeverageType = BeverageType.SPIRITS

    @classmethod
    def from_mapping(cls, data: dict) -> "ApplicationData":
        raw_type = (data.get("beverage_type") or "spirits").strip().lower()
        try:
            bev = BeverageType(raw_type)
        except ValueError:
            bev = BeverageType.SPIRITS
        return cls(
            brand_name=(data.get("brand_name") or "").strip(),
            class_type=(data.get("class_type") or "").strip(),
            alcohol_content=(data.get("alcohol_content") or "").strip(),
            net_contents=(data.get("net_contents") or "").strip(),
            bottler=(data.get("bottler") or "").strip(),
            country_of_origin=(data.get("country_of_origin") or "").strip(),
            beverage_type=bev,
        )


@dataclass
class OcrWord:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    line_key: tuple = ()


@dataclass
class OcrResult:
    words: list[OcrWord]
    text: str              # Full text, one OCR line per line.
    mean_confidence: float
    variant: str           # Which preprocessing variant produced this result.
    elapsed_ms: int

    @property
    def word_count(self) -> int:
        return len(self.words)


@dataclass
class CheckResult:
    field: str                      # machine key, e.g. "brand_name"
    label: str                      # human label, e.g. "Brand name"
    status: Status
    message: str                    # plain-language explanation for the agent
    expected: Optional[str] = None
    found: Optional[str] = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class VerificationReport:
    overall: Status
    summary: str
    checks: list[CheckResult]
    image_quality: str             # "good" | "fair" | "poor"
    image_quality_note: str
    ocr_text: str
    elapsed_ms: int

    def to_dict(self) -> dict:
        return {
            "overall": self.overall.value,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "image_quality": self.image_quality,
            "image_quality_note": self.image_quality_note,
            "ocr_text": self.ocr_text,
            "elapsed_ms": self.elapsed_ms,
        }
