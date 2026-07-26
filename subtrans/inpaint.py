"""
Hardsub removal by background reconstruction (PRD 八 AI 去字幕 · 重绘模式).

The "cover" mode simply paints a filled box over the source caption, which is
fast but leaves an obvious black bar. This module instead removes only the
*glyph pixels* and reconstructs what was behind them, so the surrounding video
survives.

No model weights are downloaded: the caption text is bright and thin, so a
per-frame mask of its strokes plus Telea inpainting follows camera motion and
lighting changes on its own, which a single static "clean plate" cannot.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

import cv2
import numpy as np

from .extractor import Segment


def _glyph_mask(gray_box: np.ndarray, bright: int = 190) -> np.ndarray:
    """Mask of caption strokes inside a caption box.

    Uses the brighter of a fixed threshold and Otsu so it copes with captions on
    both dark and light backgrounds, then dilates a little to also swallow the
    anti-aliased rim and any thin outline around each glyph.
    """
    _, fixed = cv2.threshold(gray_box, bright, 255, cv2.THRESH_BINARY)
    _, otsu = cv2.threshold(gray_box, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Prefer whichever marks less area — the caption is a minority of the box,
    # so the mask that covers everything is the wrong one.
    mask = fixed if cv2.countNonZero(fixed) <= cv2.countNonZero(otsu) else otsu
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return mask


def remove_hardsubs(
    video_in: str,
    video_out: str,
    segments: List[Segment],
    pad: int = 6,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Write a copy of ``video_in`` with the detected captions painted out.

    The result has no audio — the caller muxes the original audio back in when
    encoding the final file.
    """
    cap = cv2.VideoCapture(video_in)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_in}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    os.makedirs(os.path.dirname(os.path.abspath(video_out)) or ".", exist_ok=True)
    writer = cv2.VideoWriter(video_out, cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (w, h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Cannot open the intermediate video writer")

    # Frame ranges to clean, with their boxes.
    ranges = [(s.start, s.end, s.orig_box) for s in segments if s.orig_box]

    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps
            active = [b for (st, en, b) in ranges if st - 0.05 <= t <= en + 0.05]
            if active:
                mask = np.zeros((h, w), np.uint8)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                for (bx, by, bw, bh) in active:
                    x0, y0 = max(0, bx - pad), max(0, by - pad)
                    x1, y1 = min(w, bx + bw + pad), min(h, by + bh + pad)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    mask[y0:y1, x0:x1] = _glyph_mask(gray[y0:y1, x0:x1])
                if cv2.countNonZero(mask):
                    frame = cv2.inpaint(frame, mask, 4, cv2.INPAINT_TELEA)
            writer.write(frame)
            idx += 1
            if progress_cb and total:
                progress_cb(min(1.0, idx / total), "去除原字幕 / Removing captions")
    finally:
        cap.release()
        writer.release()
    return video_out
