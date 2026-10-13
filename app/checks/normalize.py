"""Text normalization and fuzzy search helpers.

The goal is to encode Dave's rule: "STONE'S THROW" and "Stone's Throw" are the
same thing. Differences in case, curly vs straight quotes, punctuation and
whitespace never count as a mismatch on their own.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ",
})
_NON_WORD = re.compile(r"[^0-9a-z%.]+")
_DOTS = re.compile(r"(?<!\d)\.|\.(?!\d)")  # keep decimal points, drop other dots


def clean(text: str) -> str:
    """Unicode-normalize and unify quote/dash characters, preserving case."""
    return unicodedata.normalize("NFKC", text or "").translate(_CHAR_MAP)


def tokens(text: str) -> list[str]:
    """Case-folded, punctuation-free word tokens. "Stone's Throw" -> ["stones", "throw"]."""
    t = clean(text).casefold().replace("'", "")
    t = _DOTS.sub(" ", t)
    return [w for w in _NON_WORD.split(t) if w]


def canonical(text: str) -> str:
    return " ".join(tokens(text))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


@dataclass
class Match:
    score: float       # 0..1 similarity of the normalized strings
    text: str          # the matching snippet as it appears in the OCR text
    start: int         # token index range within the source token list
    end: int


def _word_spans(text: str) -> list[tuple[str, str]]:
    """Split raw text into (raw_word, normalized_word) pairs, dropping punctuation-only words."""
    out = []
    for raw in clean(text).split():
        norm = canonical(raw)
        if norm:
            out.append((raw, norm))
    return out


def best_window_match(needle: str, haystack: str) -> Match | None:
    """Find the window of words in `haystack` most similar to `needle`.

    Windows of len(needle)±1 words are compared, so an OCR split ("OLD TOM
    DIST ILLERY") or merge ("OLDTOM") still lines up.
    """
    target = canonical(needle)
    if not target:
        return None
    n = len(target.split())
    spans = _word_spans(haystack)
    if not spans:
        return None

    best: Match | None = None
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(spans) - size + 1)):
            window = spans[i:i + size]
            cand = " ".join(norm for _, norm in window)
            score = similarity(target, cand)
            # Also compare with spaces removed, which forgives split/merged words.
            score = max(score, similarity(target.replace(" ", ""), cand.replace(" ", "")))
            if best is None or score > best.score:
                best = Match(score, " ".join(raw for raw, _ in window), i, i + size)
    return best
