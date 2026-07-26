"""
Subtitle style editor (PRD 九 字幕样式 + 十 实时修改立即刷新).

Emits ``changed`` on every edit; the window feeds that straight into the preview,
which repaints from the decoded frame — no OCR, no DeepL, no re-render.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from subtrans.style import (BG_BLACK, BG_NONE, BG_SEMI, POS_BOTTOM,
                            POS_ORIGINAL, POS_TOP, SubtitleStyle)


class ColorButton(QtWidgets.QPushButton):
    changed = QtCore.Signal(str)

    def __init__(self, color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(46, 24)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        self.setStyleSheet(
            f"background:{self._color};border:1px solid #999;border-radius:4px;")
        self.setToolTip(self._color)

    def color(self) -> str:
        return self._color

    def set_color(self, c: str):
        self._color = c
        self._refresh()

    def _pick(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self, "选择颜色")
        if c.isValid():
            self._color = c.name().upper()
            self._refresh()
            self.changed.emit(self._color)


class StylePanel(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QtWidgets.QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)
        r = 0

        self.font_combo = QtWidgets.QFontComboBox()
        self.font_combo.setCurrentFont(QtGui.QFont(self._default_font()))
        g.addWidget(QtWidgets.QLabel("字体"), r, 0)
        g.addWidget(self.font_combo, r, 1, 1, 3)
        r += 1

        self.size_spin = QtWidgets.QSpinBox()
        self.size_spin.setRange(0, 200)
        self.size_spin.setSpecialValueText("自动")
        self.size_spin.setSuffix(" px")
        g.addWidget(QtWidgets.QLabel("字号"), r, 0)
        g.addWidget(self.size_spin, r, 1)

        self.bold_cb = QtWidgets.QCheckBox("加粗")
        self.bold_cb.setChecked(True)
        g.addWidget(self.bold_cb, r, 2, 1, 2)
        r += 1

        self.color_btn = ColorButton("#FFFFFF")
        g.addWidget(QtWidgets.QLabel("字体颜色"), r, 0)
        g.addWidget(self.color_btn, r, 1)
        self.outline_btn = ColorButton("#000000")
        g.addWidget(QtWidgets.QLabel("描边颜色"), r, 2)
        g.addWidget(self.outline_btn, r, 3)
        r += 1

        self.outline_spin = QtWidgets.QSpinBox()
        self.outline_spin.setRange(0, 10)
        self.outline_spin.setValue(2)
        g.addWidget(QtWidgets.QLabel("描边粗细"), r, 0)
        g.addWidget(self.outline_spin, r, 1)

        self.shadow_spin = QtWidgets.QSpinBox()
        self.shadow_spin.setRange(0, 10)
        self.shadow_spin.setValue(1)
        g.addWidget(QtWidgets.QLabel("阴影"), r, 2)
        g.addWidget(self.shadow_spin, r, 3)
        r += 1

        self.bg_combo = QtWidgets.QComboBox()
        self.bg_combo.addItem("无", BG_NONE)
        self.bg_combo.addItem("黑底", BG_BLACK)
        self.bg_combo.addItem("半透明", BG_SEMI)
        g.addWidget(QtWidgets.QLabel("字幕背景"), r, 0)
        g.addWidget(self.bg_combo, r, 1)

        self.pos_combo = QtWidgets.QComboBox()
        self.pos_combo.addItem("原字幕位置", POS_ORIGINAL)
        self.pos_combo.addItem("顶部", POS_TOP)
        self.pos_combo.addItem("底部", POS_BOTTOM)
        g.addWidget(QtWidgets.QLabel("字幕位置"), r, 2)
        g.addWidget(self.pos_combo, r, 3)
        r += 1

        for w in (self.font_combo,):
            w.currentFontChanged.connect(lambda *_: self.changed.emit())
        for w in (self.size_spin, self.outline_spin, self.shadow_spin):
            w.valueChanged.connect(lambda *_: self.changed.emit())
        for w in (self.bg_combo, self.pos_combo):
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.bold_cb.toggled.connect(lambda *_: self.changed.emit())
        self.color_btn.changed.connect(lambda *_: self.changed.emit())
        self.outline_btn.changed.connect(lambda *_: self.changed.emit())

    @staticmethod
    def _default_font() -> str:
        import platform
        return {"Darwin": "PingFang SC", "Windows": "Microsoft YaHei"}.get(
            platform.system(), "Noto Sans CJK SC")

    # -- value <-> widgets --------------------------------------------------
    def value(self) -> SubtitleStyle:
        return SubtitleStyle(
            font=self.font_combo.currentFont().family(),
            font_size=self.size_spin.value(),
            color=self.color_btn.color(),
            outline_color=self.outline_btn.color(),
            outline_width=self.outline_spin.value(),
            shadow=self.shadow_spin.value(),
            background=self.bg_combo.currentData(),
            position=self.pos_combo.currentData(),
            bold=self.bold_cb.isChecked(),
        )

    def set_value(self, st: SubtitleStyle):
        blockers = [self.font_combo, self.size_spin, self.outline_spin,
                    self.shadow_spin, self.bg_combo, self.pos_combo, self.bold_cb]
        for w in blockers:
            w.blockSignals(True)
        self.font_combo.setCurrentFont(QtGui.QFont(st.font or self._default_font()))
        self.size_spin.setValue(st.font_size or 0)
        self.color_btn.set_color(st.color)
        self.outline_btn.set_color(st.outline_color)
        self.outline_spin.setValue(st.outline_width)
        self.shadow_spin.setValue(st.shadow)
        self._select(self.bg_combo, st.background)
        self._select(self.pos_combo, st.position)
        self.bold_cb.setChecked(st.bold)
        for w in blockers:
            w.blockSignals(False)

    @staticmethod
    def _select(combo, data):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return
