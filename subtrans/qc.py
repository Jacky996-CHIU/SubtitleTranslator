"""
Pre-export quality checks (PRD 十一 导出前智能质量检查).

Runs on the recognized + translated captions before rendering, so problems are
caught while they are still cheap to fix. Findings are advisory by default;
``blocking`` findings are the ones the UI should require acknowledging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .extractor import Segment


ERROR = "error"
WARN = "warning"


@dataclass
class Finding:
    level: str                  # ERROR | WARN
    category: str               # ocr | translate | subtitle | removal
    message: str
    caption_index: Optional[int] = None

    def __str__(self) -> str:
        where = f"[{self.caption_index:02d}] " if self.caption_index else ""
        return f"{'✕' if self.level == ERROR else '!'} {where}{self.message}"


@dataclass
class QCReport:
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.findings:
            return "检查通过，未发现问题 ✅"
        return f"发现 {len(self.errors)} 个错误、{len(self.warnings)} 个警告"


_ODD_CHARS = re.compile(r"[^\w\s%°/&\-+'’.,!?:()　-鿿＀-￯]", re.UNICODE)
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def check(
    segments: List[Segment],
    frame_size: Tuple[int, int],
    target_lang: str = "",
    burn_mode: str = "translation",
    min_conf_flagged: int = 0,
) -> QCReport:
    """Validate captions before export."""
    rep = QCReport()
    W, H = frame_size
    prev_end = -1.0
    seen: dict = {}

    for s in segments:
        idx = s.index
        text = (s.text or "").strip()
        trans = (s.translation or "").strip()

        # --- OCR ---------------------------------------------------------
        if not text:
            rep.findings.append(Finding(ERROR, "ocr", "识别结果为空", idx))
        elif len(re.sub(r"[^\w]", "", text)) < 2:
            rep.findings.append(Finding(WARN, "ocr", f"识别内容过短：{text!r}", idx))
        if text and _ODD_CHARS.search(text):
            bad = "".join(sorted(set(_ODD_CHARS.findall(text))))
            rep.findings.append(Finding(WARN, "ocr", f"含异常字符 {bad!r}", idx))
        key = re.sub(r"\W", "", text).upper()
        if key and key in seen:
            rep.findings.append(
                Finding(WARN, "ocr", f"与第 {seen[key]:02d} 条重复", idx))
        elif key:
            seen[key] = idx

        # --- translation --------------------------------------------------
        if burn_mode != "original":
            if not trans:
                rep.findings.append(Finding(ERROR, "translate", "译文为空", idx))
            elif trans == text:
                rep.findings.append(Finding(WARN, "translate", "译文与原文相同（可能未翻译）", idx))
            elif target_lang.upper().startswith("ZH") and _LATIN_WORD.search(trans):
                leftover = " ".join(_LATIN_WORD.findall(trans)[:3])
                rep.findings.append(
                    Finding(WARN, "translate", f"译文残留英文：{leftover}", idx))

        # --- subtitle geometry / timing -----------------------------------
        if s.end <= s.start:
            rep.findings.append(Finding(ERROR, "subtitle", "时间轴无效（结束≤开始）", idx))
        if s.start < prev_end - 0.01:
            rep.findings.append(Finding(WARN, "subtitle", "时间轴与上一条重叠", idx))
        prev_end = max(prev_end, s.end)

        if s.orig_box:
            bx, by, bw, bh = s.orig_box
            if bx < 0 or by < 0 or bx + bw > W or by + bh > H:
                rep.findings.append(Finding(ERROR, "subtitle", "字幕区域超出画面", idx))
            elif (bx < W * 0.02 or by < H * 0.02
                  or bx + bw > W * 0.98 or by + bh > H * 0.98):
                rep.findings.append(Finding(WARN, "subtitle", "字幕接近画面边缘（超出安全区）", idx))

        # --- removal ------------------------------------------------------
        if burn_mode == "translation" and s.orig_box is None:
            rep.findings.append(
                Finding(WARN, "removal", "未检出原字幕位置，可能残留英文", idx))

    if not segments:
        rep.findings.append(Finding(ERROR, "ocr", "没有任何字幕可导出"))
    if min_conf_flagged:
        rep.findings.append(
            Finding(WARN, "ocr", f"有 {min_conf_flagged} 条字幕置信度偏低，建议人工检查"))
    return rep
