"""OCR via Tesseract, running locally — no outbound network calls (Marcus's firewall).

`TesseractExtractor` is the only extractor today. The pipeline depends on the small
`Extractor` protocol so a different engine (e.g. an Azure-hosted vision model inside
the agency's tenant) could be swapped in without touching the checks.
"""
from __future__ import annotations

import os
import time
from typing import Protocol

# Tesseract uses OpenMP; with several labels processed in parallel, per-process
# threading just causes contention. Must be set before tesseract is invoked.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import numpy as np  # noqa: E402
import pytesseract  # noqa: E402

from app.models import OcrResult, OcrWord  # noqa: E402

TESSERACT_CONFIG = "--oem 1 --psm 3 -c preserve_interword_spaces=1"


class Extractor(Protocol):
    def extract(self, image: np.ndarray, variant: str) -> OcrResult: ...


class TesseractExtractor:
    def __init__(self, lang: str = "eng", config: str = TESSERACT_CONFIG, timeout_s: float = 8.0):
        self.lang = lang
        self.config = config
        self.timeout_s = timeout_s

    def extract(self, image: np.ndarray, variant: str) -> OcrResult:
        start = time.perf_counter()
        data = pytesseract.image_to_data(
            image, lang=self.lang, config=self.config,
            output_type=pytesseract.Output.DICT, timeout=self.timeout_s,
        )
        words: list[OcrWord] = []
        lines: dict[tuple, list[str]] = {}
        for i, raw in enumerate(data["text"]):
            text = (raw or "").strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            words.append(OcrWord(text, conf, data["left"][i], data["top"][i],
                                 data["width"][i], data["height"][i], key))
            lines.setdefault(key, []).append(text)

        full_text = "\n".join(" ".join(ws) for ws in lines.values())
        mean_conf = float(np.mean([w.conf for w in words])) if words else 0.0
        return OcrResult(words, full_text, mean_conf, variant, int((time.perf_counter() - start) * 1000))


def score(result: OcrResult) -> float:
    """Rough quality score for choosing between preprocessing variants."""
    confident = [w for w in result.words if w.conf >= 60 and len(w.text) > 1]
    return len(confident) * (result.mean_confidence / 100)
