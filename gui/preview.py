"""
Real-time preview (PRD 十 实时预览).

Draws a video frame with the black cover boxes and the translated caption on
top, using the current :class:`SubtitleStyle`. Restyling repaints from the
already-decoded frame, so changing font / size / colour / position is instant and
never re-runs OCR or DeepL.

Qt does the text drawing here rather than ffmpeg/libass: it is fast enough to be
interactive, and the geometry (centre of the cover box, size scaled to the box)
matches what the exporter writes into the ASS file.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from subtrans.style import BG_BLACK, BG_SEMI, POS_BOTTOM, POS_ORIGINAL, POS_TOP, SubtitleStyle


def _qcolor(hex_rgb: str) -> QtGui.QColor:
    c = QtGui.QColor(hex_rgb)
    return c if c.isValid() else QtGui.QColor("#FFFFFF")


class PreviewWidget(QtWidgets.QWidget):
    """Video preview with play / pause / seek and live restyling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap: Optional[cv2.VideoCapture] = None
        self._path = ""
        self._fps = 25.0
        self._frames = 0
        self._frame: Optional[np.ndarray] = None
        self._pos = 0                       # current frame index
        self.segments: List = []
        self.cover_windows: List[Tuple[float, float, tuple]] = []
        self.style = SubtitleStyle()
        self.show_translation = True

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._advance)

        self.canvas = QtWidgets.QLabel("处理完成后在这里预览")
        self.canvas.setAlignment(QtCore.Qt.AlignCenter)
        self.canvas.setMinimumHeight(300)
        self.canvas.setStyleSheet(
            "background:#111;color:#888;border-radius:6px;")

        self.play_btn = QtWidgets.QPushButton("▶ 播放")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle_play)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.seek_frame)
        self.slider.valueChanged.connect(self.seek_frame)

        self.time_lbl = QtWidgets.QLabel("00:00 / 00:00")
        self.time_lbl.setStyleSheet("color:#666;")

        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.play_btn)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time_lbl)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(bar)

    # -- source -------------------------------------------------------------
    def open(self, path: str):
        self.close_video()
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            self._cap = None
            return False
        self._path = path
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.slider.setRange(0, max(0, self._frames - 1))
        self.slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.seek_frame(0)
        return True

    def close_video(self):
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._frame = None

    # -- playback -----------------------------------------------------------
    def toggle_play(self):
        if self._cap is None:
            return
        if self._timer.isActive():
            self._timer.stop()
            self.play_btn.setText("▶ 播放")
        else:
            self._timer.start(int(1000 / max(1.0, min(self._fps, 30.0))))
            self.play_btn.setText("⏸ 暂停")

    def _advance(self):
        if self._cap is None:
            return
        if self._pos + 1 >= self._frames:
            self.toggle_play()
            return
        self.seek_frame(self._pos + 1, from_timer=True)

    def seek_frame(self, idx: int, from_timer: bool = False):
        if self._cap is None:
            return
        idx = max(0, min(int(idx), max(0, self._frames - 1)))
        if not from_timer or idx != self._pos + 1:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self._cap.read()
        if not ok:
            return
        self._pos = idx
        self._frame = frame
        if self.slider.value() != idx:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
        self.time_lbl.setText(
            f"{self._fmt(idx / self._fps)} / {self._fmt(self._frames / self._fps)}")
        self.repaint_frame()

    @staticmethod
    def _fmt(sec: float) -> str:
        m, s = divmod(int(max(0, sec)), 60)
        return f"{m:02d}:{s:02d}"

    # -- rendering ----------------------------------------------------------
    def apply_style(self, style: SubtitleStyle):
        """Restyle without touching OCR or translation — just repaint."""
        self.style = style
        self.repaint_frame()

    def repaint_frame(self):
        if self._frame is None:
            return
        t = self._pos / self._fps
        img = self._frame
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w,
                            QtGui.QImage.Format_RGB888).copy()

        painter = QtGui.QPainter(qimg)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        try:
            self._draw_cover(painter, t, w, h)
            self._draw_caption(painter, t, w, h)
        finally:
            painter.end()

        pix = QtGui.QPixmap.fromImage(qimg)
        self.canvas.setPixmap(pix.scaled(
            self.canvas.width(), self.canvas.height(),
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _draw_cover(self, painter, t: float, w: int, h: int, pad: int = 8):
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0))
        for (st, en, box) in self.cover_windows:
            if not (st <= t <= en):
                continue
            x, y, bw, bh = box
            x, y = max(0, x - pad), max(0, y - pad)
            painter.drawRect(x, y, min(w - x, bw + 2 * pad),
                             min(h - y, bh + 2 * pad))

    def _active_segment(self, t: float):
        for s in self.segments:
            if s.start <= t <= s.end:
                return s
        return None

    def _draw_caption(self, painter, t: float, w: int, h: int):
        seg = self._active_segment(t)
        if seg is None:
            return
        text = (seg.translation or seg.text) if self.show_translation else seg.text
        if not text:
            return
        lines = [l for l in text.split("\n") if l.strip()]
        st = self.style

        box = seg.orig_box
        if st.position == POS_ORIGINAL and box:
            bx, by, bw, bh = box
            size = st.font_size or max(12, int(bh / max(1, len(lines)) * 0.78))
            cx, cy = bx + bw / 2, by + bh / 2
        else:
            size = st.resolved_font_size(h)
            cx = w / 2
            cy = (st.margin_v + size * len(lines) / 2) if st.position == POS_TOP \
                else (h - st.margin_v - size * len(lines) / 2)

        font = QtGui.QFont(st.font or "Arial")
        font.setPixelSize(int(size))
        font.setBold(st.bold)
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)
        line_h = fm.height()
        total_h = line_h * len(lines)
        top = cy - total_h / 2

        if st.background in (BG_BLACK, BG_SEMI):
            widest = max(fm.horizontalAdvance(l) for l in lines)
            bg = QtGui.QColor(0, 0, 0, 255 if st.background == BG_BLACK else 128)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRect(int(cx - widest / 2 - 8), int(top - 4),
                             int(widest + 16), int(total_h + 8))

        fill = _qcolor(st.color)
        stroke = _qcolor(st.outline_color)
        for i, line in enumerate(lines):
            adv = fm.horizontalAdvance(line)
            x = cx - adv / 2
            y = top + line_h * i + fm.ascent()
            path = QtGui.QPainterPath()
            path.addText(QtCore.QPointF(x, y), font, line)
            if st.shadow:
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(0, 0, 0, 160))
                painter.translate(st.shadow, st.shadow)
                painter.drawPath(path)
                painter.translate(-st.shadow, -st.shadow)
            if st.outline_width > 0:
                pen = QtGui.QPen(stroke, st.outline_width * 2)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawPath(path)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPath(path)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.repaint_frame()
