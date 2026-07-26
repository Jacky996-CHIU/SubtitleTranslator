"""
Cover-box measurement for the original hardsub (PRD 八 覆盖模式).

``Segment.orig_box`` is a *median* box across the frames of a caption, which is
the right choice for deciding where to draw the replacement text but too small
to reliably hide the source text: a single frame where the caption was wider
(or where OCR clipped a line) leaves English pixels sticking out of the mask.

This module re-measures each caption by scanning its own frames and taking the
**union** of the actual bright-text extent, so the black box always covers the
whole original caption.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .extractor import Segment


def _text_extent(gray_roi: np.ndarray, ref_h: int,
                 bright: int = 185) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of caption-like bright text inside a ROI, or None."""
    _, mask = cv2.threshold(gray_roi, bright, 255, cv2.THRESH_BINARY)
    if cv2.countNonZero(mask) < 8:
        return None
    # Join glyphs into words/lines so isolated specks don't count as text.
    joined = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    cnts, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    x0 = y0 = 10 ** 6
    x1 = y1 = -1
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if h < max(4, ref_h * 0.25) or h > ref_h * 2.2:
            continue                      # not a caption line
        if w < 6:
            continue
        x0, y0 = min(x0, x), min(y0, y)
        x1, y1 = max(x1, x + w), max(y1, y + h)
    if x1 < 0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def refine_cover_boxes(
    video_path: str,
    segments: List[Segment],
    search_margin: int = 14,
    samples_per_segment: int = 14,
) -> Dict[int, Tuple[int, int, int, int]]:
    """Per-caption box that fully covers the original text.

    Only a bounded neighbourhood of the detected box is searched, so bright
    background objects elsewhere in the frame can never inflate the mask.
    """
    boxes: Dict[int, Tuple[int, int, int, int]] = {}
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return boxes
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    try:
        for s in segments:
            if not s.orig_box:
                continue
            bx, by, bw, bh = s.orig_box
            rx0 = max(0, bx - search_margin)
            ry0 = max(0, by - search_margin)
            rx1 = min(W, bx + bw + search_margin)
            ry1 = min(H, by + bh + search_margin)
            if rx1 <= rx0 or ry1 <= ry0:
                continue

            ux0, uy0, ux1, uy1 = bx, by, bx + bw, by + bh   # start from OCR box
            n = max(2, min(samples_per_segment,
                           int((s.end - s.start) * fps) or 2))
            for k in range(n):
                t = s.start + (s.end - s.start) * (k / max(1, n - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
                ok, frame = cap.read()
                if not ok:
                    continue
                roi = cv2.cvtColor(frame[ry0:ry1, rx0:rx1], cv2.COLOR_BGR2GRAY)
                ext = _text_extent(roi, ref_h=max(6, bh // max(1, _lines(s))))
                if not ext:
                    continue
                ex, ey, ew, eh = ext
                ux0 = min(ux0, rx0 + ex)
                uy0 = min(uy0, ry0 + ey)
                ux1 = max(ux1, rx0 + ex + ew)
                uy1 = max(uy1, ry0 + ey + eh)
            boxes[s.index] = (int(ux0), int(uy0),
                              int(ux1 - ux0), int(uy1 - uy0))
    finally:
        cap.release()
    return boxes


def _lines(seg: Segment) -> int:
    return max(1, len([l for l in (seg.text or "").split("\n") if l.strip()]))
