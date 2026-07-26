"""
Subtitle extraction pipeline.

Samples frames from a video, OCRs the burned-in captions, groups consecutive
frames carrying the same caption into timed segments, and picks the best text
for each segment by majority vote across its frames (so animation / fade
frames cannot corrupt the result).

A frame-difference short-circuit avoids re-running OCR on near-identical
consecutive frames: captions stay static for seconds, so most sampled frames
reuse the previous OCR result. This keeps extraction fast.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, List, Optional

import cv2
import numpy as np

from .ocr_engine import BaseOCR, OCRConfig, build_engine
from .ocr_postprocess import correct_text, dedupe_lines


@dataclass
class Segment:
    index: int
    start: float          # seconds
    end: float            # seconds
    text: str             # original caption (lines joined by "\n")
    translation: str = ""
    # Union bounding box (x, y, w, h) of the original burned-in caption, in
    # frame pixels. Used to mask the source caption on re-render. None if unknown.
    orig_box: Optional[tuple] = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    return inter / float(aw * ah + bw * bh - inter)


def _build_cover_windows(samples, step_pad: float = 0.15,
                         stable_iou: float = 0.5):
    """Turn per-frame caption boxes into (start, end, box) mask windows.

    Boxes come from OCR lines that already passed confidence and shape checks,
    so they hug the real text instead of guessing from bright pixels. All lines
    present at one sample time are unioned, then consecutive times are merged
    while the union stays similar, which keeps each mask tight.
    """
    per_time = []
    for t, _lines, boxes in samples:
        if not boxes:
            per_time.append((t, None))
            continue
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[0] + b[2] for b in boxes)
        y1 = max(b[1] + b[3] for b in boxes)
        per_time.append((t, (x0, y0, x1 - x0, y1 - y0)))

    windows = []
    start = end = None
    cur = None
    for t, box in per_time:
        if box is None:
            if start is not None:
                windows.append((max(0.0, start - step_pad), end + step_pad, cur))
                start = cur = None
            continue
        if start is None:
            start, end, cur = t, t, box
            continue
        # Union every box seen while text is continuously present. Splitting on
        # box similarity looked tighter but leaked: a 3-line caption whose
        # middle frames only detected one line left the other lines uncovered.
        # Windows still break whenever a sample sees no text at all, which is
        # what separates one caption from the next.
        if t - end > max(0.6, step_pad * 4):
            windows.append((max(0.0, start - step_pad), end + step_pad, cur))
            start, end, cur = t, t, box
            continue
        cur = (min(cur[0], box[0]), min(cur[1], box[1]),
               max(cur[0] + cur[2], box[0] + box[2]) - min(cur[0], box[0]),
               max(cur[1] + cur[3], box[1] + box[3]) - min(cur[1], box[1]))
        end = t
    if start is not None:
        windows.append((max(0.0, start - step_pad), end + step_pad, cur))
    return windows


@dataclass
class ExtractConfig:
    sample_fps: float = 4.0          # frames sampled per second
    merge_similarity: float = 0.6    # >= this ratio => same caption
    min_duration: float = 0.5        # drop segments shorter than this (s)
    diff_threshold: float = 0.02     # caption-region change fraction to re-OCR
    # Reusing a previous frame's OCR result for visually similar frames is
    # faster but loses caption lines that were missed on the first frame of a
    # caption. Accuracy is P0, so this is off by default.
    reuse_similar_frames: bool = False


class SubtitleExtractor:
    def __init__(
        self,
        engine: Optional[BaseOCR] = None,
        ocr_config: Optional[OCRConfig] = None,
        config: Optional[ExtractConfig] = None,
    ):
        self.engine = engine or build_engine("tesseract", ocr_config)
        # (start, end, box) windows for masking the original captions.
        self.cover_windows: List[tuple] = []
        self.cfg = config or ExtractConfig()

    # -- internal helpers ---------------------------------------------------

    def _region_signature(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Small binary thumbnail of the caption band, for cheap diffing."""
        cc = self.engine.config
        H, W = frame_bgr.shape[:2]
        band = frame_bgr[int(H * cc.region_top):, :]
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        _, white = cv2.threshold(gray, cc.white_threshold, 255, cv2.THRESH_BINARY)
        return cv2.resize(white, (64, 24), interpolation=cv2.INTER_AREA)

    # -- public API ---------------------------------------------------------

    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> List[Segment]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps / self.cfg.sample_fps)))

        samples: List[tuple] = []       # (time, lines, boxes)
        prev_sig = None
        prev_lines: List[str] = []
        prev_boxes: List[tuple] = []
        i = 0
        while True:
            grabbed = cap.grab()
            if not grabbed:
                break
            if i % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    sig = self._region_signature(frame)
                    if prev_sig is not None:
                        diff = np.mean(np.abs(sig.astype(np.int16) -
                                              prev_sig.astype(np.int16))) / 255.0
                    else:
                        diff = 1.0
                    # Accuracy over speed (PRD P0): re-OCR every sampled frame.
                    # Reusing the previous frame's result poisoned whole
                    # captions — if the first frame of a caption was only
                    # partially detected (e.g. during a fade-in), every later
                    # "similar" frame reused that partial text and the missing
                    # line could never be recovered by the vote.
                    if (self.cfg.reuse_similar_frames
                            and diff < self.cfg.diff_threshold
                            and prev_sig is not None):
                        lines = prev_lines          # reuse — caption unchanged
                        boxes = prev_boxes
                    else:
                        lines = self.engine.detect_lines(frame)
                        boxes = list(self.engine.last_boxes)
                        prev_lines, prev_boxes = lines, boxes
                        prev_sig = sig
                    samples.append((i / fps, lines, boxes))
                    if progress_cb and total:
                        progress_cb(min(0.99, i / total), "识别字幕中 / Recognizing")
            i += 1
        cap.release()

        segments = self._segment(samples)
        # Mask windows straight from the per-frame boxes OCR already accepted:
        # every line visible at a given moment is covered, regardless of how the
        # lines were later grouped into segments.
        self.cover_windows = _build_cover_windows(samples)
        if progress_cb:
            progress_cb(1.0, "识别完成 / Recognition done")
        return segments

    def _segment(self, samples: List[tuple]) -> List[Segment]:
        cfg = self.cfg
        raw = []
        cur = None
        for t, lines, boxes in samples:
            text = "\n".join(lines).strip()
            key = _norm(text)
            if cur is not None and text and (
                _similar(text, cur["rep"]) >= cfg.merge_similarity
                or (key and cur["repkey"] and (key in cur["repkey"] or cur["repkey"] in key))
            ):
                cur["end"] = t
                cur["samples"].append(text)
                if boxes:
                    cur["boxes"].append(boxes)
                if len(key) > len(cur["repkey"]):
                    cur["rep"], cur["repkey"] = text, key
            else:
                if cur and cur["repkey"]:
                    raw.append(cur)
                cur = {"start": t, "end": t, "rep": text, "repkey": key,
                       "samples": [text] if text else [],
                       "boxes": [boxes] if boxes else []}
        if cur and cur["repkey"]:
            raw.append(cur)

        # majority vote + build segments
        segs: List[Segment] = []
        for g in raw:
            text = self._vote(g["samples"])
            if not _norm(text) or (g["end"] - g["start"]) < cfg.min_duration:
                continue
            box = self._union_box(g["boxes"])
            segs.append(Segment(0, round(g["start"], 2), round(g["end"], 2), text,
                                orig_box=box))

        # De-duplicate repeated lines inside one caption and fix common OCR
        # confusions (PRD: 去重 / OCR 自动纠错).
        for s in segs:
            lines = dedupe_lines([l for l in s.text.split("\n") if l.strip()])
            s.text = correct_text("\n".join(lines))
        segs = [s for s in segs if _norm(s.text)]

        # merge adjacent segments with the same voted text (fixes brief gaps)
        merged: List[Segment] = []
        for s in segs:
            if merged and _similar(s.text, merged[-1].text) >= 0.85 \
                    and s.start - merged[-1].end < 1.0:
                merged[-1].end = s.end
                merged[-1].orig_box = self._merge_box(merged[-1].orig_box, s.orig_box)
            else:
                merged.append(s)
        for idx, s in enumerate(merged, 1):
            s.index = idx
        return merged

    @staticmethod
    def _union_box(box_frames: List[List[tuple]]):
        """Median union box over a segment's frames (robust to outliers)."""
        x1s, y1s, x2s, y2s = [], [], [], []
        for boxes in box_frames:
            if not boxes:
                continue
            x1 = min(b[0] for b in boxes)
            y1 = min(b[1] for b in boxes)
            x2 = max(b[0] + b[2] for b in boxes)
            y2 = max(b[1] + b[3] for b in boxes)
            x1s.append(x1); y1s.append(y1); x2s.append(x2); y2s.append(y2)
        if not x1s:
            return None
        med = lambda a: sorted(a)[len(a) // 2]
        x1, y1, x2, y2 = med(x1s), med(y1s), med(x2s), med(y2s)
        return (x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def _merge_box(a, b):
        if a is None:
            return b
        if b is None:
            return a
        x1 = min(a[0], b[0]); y1 = min(a[1], b[1])
        x2 = max(a[0] + a[2], b[0] + b[2]); y2 = max(a[1] + a[3], b[1] + b[3])
        return (x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def _vote(samples: List[str], support: float = 0.4) -> str:
        """Pick the most representative caption text among a segment's frames.

        Lines are clustered across frames by similarity. Only clusters that
        appear in at least ``support`` of the frames are kept — this drops
        flicker noise (background logos, device readouts) that a real caption,
        which persists across the whole segment, always beats. Kept lines are
        ordered by their average vertical position within the frame.
        """
        frame_lines = []
        for s in samples:
            parts = [p.strip() for p in s.split("\n") if _norm(p)]
            if parts:
                frame_lines.append(parts)
        n = len(frame_lines)
        if n == 0:
            return ""

        clusters = []  # each: {canon, variants Counter, frames set, pos list}
        for fi, parts in enumerate(frame_lines):
            for pi, line in enumerate(parts):
                best = None
                for cl in clusters:
                    if _similar(line, cl["canon"]) >= 0.8:
                        best = cl
                        break
                if best is None:
                    best = {"canon": line, "variants": Counter(),
                            "frames": set(), "pos": []}
                    clusters.append(best)
                best["variants"][line] += 1
                best["frames"].add(fi)
                best["pos"].append(pi)
                # canonical = most common exact variant so far
                best["canon"] = best["variants"].most_common(1)[0][0]

        kept = []
        for cl in clusters:
            frac = len(cl["frames"]) / n
            canon = cl["canon"]
            alpha = len(re.sub(r"[^A-Za-z]", "", canon))
            if frac >= support and alpha >= 3:
                kept.append((sum(cl["pos"]) / len(cl["pos"]), canon))
        if not kept:
            # fall back to the single most frequent line
            allc = Counter()
            for parts in frame_lines:
                for line in parts:
                    allc[line] += 1
            return allc.most_common(1)[0][0] if allc else ""
        kept.sort()
        return "\n".join(c for _, c in kept).strip()
