"""
Post-processing for OCR output: de-duplication, context-aware correction and a
quality score.

These run after recognition and voting, on the assembled caption text, so they
never cost another OCR pass (PRD: 修改样式禁止重新 OCR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Tuple


# --------------------------------------------------------------------------- #
# De-duplication
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def dedupe_lines(lines: List[str], similarity: float = 0.92) -> List[str]:
    """Drop lines that merely repeat another line of the same caption.

    Partial detections make a caption's own line show up twice, once truncated:
    ``["FUSE BOX CIRCUIT", "FUSE BOX CIRCUIT TEST"]`` or
    ``["CURRENT TEST", "TEST"]``. Keep the longest form and drop anything that
    is contained in it or near-identical to it.
    """
    kept: List[str] = []
    for line in lines:
        n = _norm(line)
        if not n:
            continue
        replaced = False
        drop = False
        for i, other in enumerate(kept):
            o = _norm(other)
            if n == o or n in o or SequenceMatcher(None, n, o).ratio() >= similarity:
                drop = True                      # already covered by `other`
                break
            if o in n:                           # this line is the fuller form
                kept[i] = line
                replaced = True
                break
        if not drop and not replaced:
            kept.append(line)
    return kept


# --------------------------------------------------------------------------- #
# Context-aware character correction
# --------------------------------------------------------------------------- #
# Only applied when the confusable character sits *between letters*, so real
# numbers ("1080P", "25,000-COUNT", "IP67") are never touched.
_LETTER_CONTEXT = [
    (re.compile(r"(?<=[A-Za-z])0(?=[A-Za-z])"), "O"),
    (re.compile(r"(?<=[A-Za-z])1(?=[A-Za-z])"), "I"),
    (re.compile(r"(?<=[A-Za-z])5(?=[A-Za-z])"), "S"),
    (re.compile(r"(?<=[A-Za-z])8(?=[A-Za-z])"), "B"),
    (re.compile(r"\|"), "I"),
]

# Word-initial confusions: a lone digit starting an otherwise alphabetic word.
_WORD_INITIAL = [
    (re.compile(r"\b0(?=[A-Za-z]{2,})"), "O"),
    (re.compile(r"\b5(?=[A-Za-z]{2,})"), "S"),
]


def correct_text(text: str) -> str:
    """Fix common OCR confusions and strip noise punctuation, line by line."""
    out_lines = []
    for line in text.split("\n"):
        s = line
        for rx, rep in _LETTER_CONTEXT:
            s = rx.sub(rep, s)
        for rx, rep in _WORD_INITIAL:
            s = rx.sub(rep, s)
        # Collapse an immediately repeated word ("TEST TEST" -> "TEST").
        s = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", s, flags=re.IGNORECASE)
        # Strip stray leading/trailing punctuation left by speckle.
        s = re.sub(r"^[\s.,:;'’\-|]+", "", s)
        s = re.sub(r"[\s.,:;'’|]+$", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        if s:
            out_lines.append(s)
    return "\n".join(out_lines)


# --------------------------------------------------------------------------- #
# Quality score
# --------------------------------------------------------------------------- #
@dataclass
class OCRQuality:
    caption_count: int = 0
    mean_confidence: float = 0.0
    low_conf_count: int = 0          # captions below the review threshold
    review_suggested: int = 0        # captions a human should eyeball
    score: float = 0.0               # 0..100 overall

    def summary(self) -> str:
        return (f"字幕 {self.caption_count} 条 · 平均置信度 {self.mean_confidence:.1f} "
                f"· 低置信 {self.low_conf_count} 条 · 建议人工检查 {self.review_suggested} 条 "
                f"· 综合评分 {self.score:.0f}/100")


_SUSPICIOUS = re.compile(r"[^A-Za-z0-9%°/&\-+'’.,!?:() \n]")


def score_captions(texts: List[str], line_confidences: List[float],
                   low_conf: float = 70.0) -> OCRQuality:
    """Summarize recognition quality (PRD: OCR 质量评分).

    ``line_confidences`` are per-recognized-line and need not line up with
    ``texts`` (one caption can hold several lines), so confidence drives the
    aggregate numbers while per-caption review flags come from the text itself.
    """
    q = OCRQuality(caption_count=len(texts))
    if line_confidences:
        q.mean_confidence = sum(line_confidences) / len(line_confidences)
        q.low_conf_count = sum(1 for c in line_confidences if c < low_conf)
    review = 0
    for t in texts:
        if _SUSPICIOUS.search(t) or len(_norm(t)) < 3:
            review += 1
    # A globally weak recognition deserves review even if the text looks clean.
    if q.mean_confidence and q.mean_confidence < low_conf:
        review = max(review, q.low_conf_count)
    q.review_suggested = review
    if q.caption_count:
        conf_part = max(0.0, min(1.0, (q.mean_confidence - 50.0) / 45.0))
        clean_part = 1.0 - (review / q.caption_count)
        q.score = round(100.0 * (0.65 * conf_part + 0.35 * clean_part), 1)
    return q
