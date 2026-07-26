"""
OCR engines for detecting burned-in (hardcoded) captions in video frames.

Two backends are provided:

* ``TesseractOCR``  – lightweight, no heavy ML deps, bundles easily into a
  desktop app. Uses a white-text mask + morphological line grouping so that
  large bottom-anchored captions are isolated from background clutter and each
  caption line is OCR'd in correct reading order. This is the default engine
  and the one used for the project's built-in verification.

* ``PaddleOCR``    – optional high-accuracy engine based on PP-OCR. Only used
  when the ``paddleocr`` package is installed on the user's machine. Returns
  detection boxes with confidence, which are filtered by height / position so
  captions are separated from small on-screen device text.

Both engines expose the same interface::

    engine.detect_lines(frame_bgr) -> list[str]   # top-to-bottom caption lines

All engines are configured by an :class:`OCRConfig` describing where captions
live (region), how large they are, and brightness of the text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List

from .runtime_paths import find_tool, tessdata_dir

import cv2
import numpy as np


# Characters we allow through for latin-script captions. Anything else is
# almost always OCR noise from textured backgrounds.
_ALLOWED = re.compile(r"[^A-Za-z0-9%°/&\-+'’.,!?:() ]")


def clean_line(text: str) -> str:
    """Strip OCR noise characters and collapse whitespace."""
    text = _ALLOWED.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Drop stray single punctuation fragments.
    if len(re.sub(r"[^A-Za-z0-9]", "", text)) < 2:
        return ""
    return text


@dataclass
class OCRConfig:
    """Where captions live and how they look. All fractions are 0..1."""

    # Vertical band to search for captions (fraction of frame height).
    region_top: float = 0.45
    region_bottom: float = 1.0
    # Caption glyph height as a fraction of frame height.
    min_line_height: float = 0.05
    max_line_height: float = 0.24
    # Minimum caption line width as a fraction of frame width.
    min_line_width: float = 0.12
    # Brightness threshold for the "white text" mask (0..255).
    white_threshold: int = 200
    # Horizontal dilation (px, pre-scale) used to merge characters into a line.
    merge_kernel_w: int = 25
    # Upscale factor applied to each cropped line before recognition.
    upscale: int = 3
    # Minimum mean per-line OCR confidence (0..100) to accept a caption line.
    min_conf: float = 62.0
    # If True, prefer/keep upper-case style captions and reject mostly
    # lower-case fragments (typical of background logos / UI chrome). Marketing
    # captions like these are all-caps; general subtitles may not be, so this
    # is a soft score, not a hard reject.
    uppercase_bias: bool = True


class BaseOCR:
    name = "base"

    def __init__(self, config: OCRConfig | None = None):
        self.config = config or OCRConfig()
        # Bounding boxes (x, y, w, h) of the caption lines accepted by the most
        # recent detect_lines() call, in frame pixel coords. Used to mask the
        # original burned-in caption when re-rendering the video.
        self.last_boxes: List[tuple] = []

    def detect_lines(self, frame_bgr: np.ndarray) -> List[str]:  # pragma: no cover
        raise NotImplementedError


class TesseractOCR(BaseOCR):
    """Default caption OCR using Tesseract + morphological line detection."""

    name = "tesseract"

    def __init__(self, config: OCRConfig | None = None, lang: str = "eng"):
        super().__init__(config)
        self.lang = lang
        import pytesseract  # imported here so the module import stays cheap

        # When frozen, use the ffmpeg/tesseract binaries bundled inside the app
        # so end users don't need to install anything.
        tcmd = find_tool("tesseract")
        if tcmd:
            pytesseract.pytesseract.tesseract_cmd = tcmd
        tdir = tessdata_dir()
        if tdir:
            os.environ.setdefault("TESSDATA_PREFIX", tdir)

        self._tess = pytesseract

    def _line_boxes(self, gray: np.ndarray):
        cfg = self.config
        H, W = gray.shape
        _, white = cv2.threshold(gray, cfg.white_threshold, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (cfg.merge_kernel_w, 3))
        dil = cv2.dilate(white, kernel, iterations=1)
        cnts, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if h < H * cfg.min_line_height or h > H * cfg.max_line_height:
                continue
            if w < W * cfg.min_line_width:
                continue
            if (y + h) < H * cfg.region_top:
                continue
            if y > H * cfg.region_bottom:
                continue
            fill = cv2.countNonZero(white[y : y + h, x : x + w]) / float(w * h + 1)
            if fill < 0.07 or fill > 0.62:
                continue
            boxes.append((y, x, w, h))
        boxes.sort()  # top-to-bottom
        return boxes

    def _ocr_line(self, cth) -> tuple[str, float]:
        """Return (cleaned_text, mean_confidence) for one prepared line crop."""
        from pytesseract import Output

        data = self._tess.image_to_data(
            cth, lang=self.lang, config="--psm 7", output_type=Output.DICT
        )
        words, confs = [], []
        for t, c in zip(data["text"], data["conf"]):
            t = t.strip()
            if not t:
                continue
            try:
                cf = float(c)
            except ValueError:
                cf = -1.0
            if cf >= 0:
                words.append(t)
                confs.append(cf)
        text = clean_line(" ".join(words))
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        return text, mean_conf

    def _caption_ok(self, text: str, conf: float) -> bool:
        cfg = self.config
        if not text or conf < cfg.min_conf:
            return False
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 3:
            return False
        if cfg.uppercase_bias:
            upper = sum(1 for c in letters if c.isupper())
            # captions are predominantly upper-case; background chrome is not.
            if upper / len(letters) < 0.6:
                return False
        return True

    def detect_lines(self, frame_bgr: np.ndarray) -> List[str]:
        cfg = self.config
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        out: List[str] = []
        boxes: List[tuple] = []
        for (y, x, w, h) in self._line_boxes(gray):
            pad = max(6, h // 6)
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(H, y + h + pad), min(W, x + w + pad)
            crop = gray[y0:y1, x0:x1]
            crop = cv2.resize(
                crop, None, fx=cfg.upscale, fy=cfg.upscale, interpolation=cv2.INTER_CUBIC
            )
            _, cth = cv2.threshold(crop, cfg.white_threshold, 255, cv2.THRESH_BINARY)
            cth = cv2.copyMakeBorder(cth, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=0)
            txt, conf = self._ocr_line(cth)
            if self._caption_ok(txt, conf):
                out.append(txt)
                boxes.append((int(x), int(y), int(w), int(h)))
        self.last_boxes = boxes
        return out


class PaddleOCR(BaseOCR):
    """Optional high-accuracy engine. Requires ``paddleocr`` to be installed."""

    name = "paddleocr"

    def __init__(self, config: OCRConfig | None = None, lang: str = "en"):
        super().__init__(config)
        from paddleocr import PaddleOCR as _Paddle  # type: ignore

        # angle classifier off (captions are horizontal); det+rec on.
        self._ocr = _Paddle(use_angle_cls=False, lang=lang, show_log=False)

    def detect_lines(self, frame_bgr: np.ndarray) -> List[str]:
        cfg = self.config
        H, W = frame_bgr.shape[:2]
        result = self._ocr.ocr(frame_bgr, cls=False)
        if not result or not result[0]:
            return []
        rows = []
        for box, (text, conf) in result[0]:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            top, bottom = min(ys), max(ys)
            left, right = min(xs), max(xs)
            height = bottom - top
            if conf < 0.6:
                continue
            if height < H * cfg.min_line_height or height > H * cfg.max_line_height:
                continue
            if bottom < H * cfg.region_top:
                continue
            t = clean_line(text)
            if t:
                rows.append((top, left, t,
                             (int(left), int(top), int(right - left), int(height))))
        rows.sort(key=lambda r: (r[0], r[1]))
        self.last_boxes = [r[3] for r in rows]
        return [r[2] for r in rows]


def build_engine(name: str = "tesseract", config: OCRConfig | None = None,
                 lang: str | None = None) -> BaseOCR:
    """Factory. ``name`` is 'tesseract' or 'paddleocr'."""
    name = (name or "tesseract").lower()
    if name == "paddleocr":
        return PaddleOCR(config, lang=lang or "en")
    return TesseractOCR(config, lang=lang or "eng")
