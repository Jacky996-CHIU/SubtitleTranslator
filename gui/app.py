"""
AI Subtitle Studio — desktop GUI (PySide6).

Recognizes burned-in English captions, translates them with DeepL, masks the
originals and draws the translation in their place, then exports MP4 / SRT.

The window follows the PRD's flow top to bottom:
导入视频 → 目标语言 → 字幕样式 → 开始处理 → 预览 → 导出

Processing is split in two so restyling is free: **分析** runs OCR + translation
once (cached), **导出** only renders. Changing any style control repaints the
preview immediately and never re-runs recognition or translation.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Allow running from source tree.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from subtrans.pipeline import JobConfig, run_job  # noqa: E402
from subtrans.settings import Settings  # noqa: E402
from subtrans.style import SubtitleStyle  # noqa: E402

from preview import PreviewWidget  # noqa: E402
from style_panel import StylePanel  # noqa: E402


APP_NAME = "AI Subtitle Studio"

TARGETS = [
    ("ZH", "中文（简体）"), ("ZH-HANT", "中文（繁體）"),
    ("EN-US", "英语（美国）"), ("EN-GB", "英语（英国）"),
    ("JA", "日语"), ("KO", "韩语"), ("DE", "德语"), ("FR", "法语"),
    ("ES", "西班牙语"), ("IT", "意大利语"), ("PT-BR", "葡萄牙语（巴西）"),
    ("PT-PT", "葡萄牙语（葡萄牙）"), ("RU", "俄语"), ("NL", "荷兰语"),
    ("PL", "波兰语"), ("TR", "土耳其语"), ("AR", "阿拉伯语"),
    ("ID", "印尼语"), ("UK", "乌克兰语"), ("CS", "捷克语"),
    ("DA", "丹麦语"), ("FI", "芬兰语"), ("EL", "希腊语"),
    ("HU", "匈牙利语"), ("NB", "挪威语"), ("RO", "罗马尼亚语"),
    ("SK", "斯洛伐克语"), ("SV", "瑞典语"), ("BG", "保加利亚语"),
]


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{int(m):02d}:{s:04.1f}"
    return f"{int(m):02d}:{s:04.1f}"


def show_error(parent, msg: str):
    """Bounded, scrollable, always-closable error dialog."""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(APP_NAME + " — 出错")
    dlg.resize(680, 420)
    lay = QtWidgets.QVBoxLayout(dlg)
    head = QtWidgets.QLabel("处理时出错了，详情如下（可滚动、可复制）：")
    head.setStyleSheet("font-weight:700;")
    lay.addWidget(head)
    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(msg)
    box.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    box.setStyleSheet("font-family:Menlo,Consolas,monospace;font-size:12px;")
    lay.addWidget(box, 1)
    btns = QtWidgets.QHBoxLayout()
    cp = QtWidgets.QPushButton("复制")
    cp.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(msg))
    cl = QtWidgets.QPushButton("关闭")
    cl.setDefault(True)
    cl.clicked.connect(dlg.accept)
    btns.addWidget(cp)
    btns.addStretch(1)
    btns.addWidget(cl)
    lay.addLayout(btns)
    dlg.exec()


# --------------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------------- #
class Worker(QtCore.QThread):
    """Runs one run_job() call off the UI thread."""

    progress = QtCore.Signal(float, str)
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, cfg: JobConfig):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            result = run_job(self.cfg, progress_cb=lambda p, m:
                             self.progress.emit(p, m))
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.video = ""
        self.result = None
        self.worker: Worker | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 860)
        self._build_ui()
        self._load_settings()

    # -- construction -------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # ---------- left: the flow ----------
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)

        title = QtWidgets.QLabel(APP_NAME)
        title.setStyleSheet("font-size:19px;font-weight:700;")
        left.addWidget(title)
        sub = QtWidgets.QLabel("识别硬字幕 → DeepL 翻译 → 覆盖原字幕 → 导出")
        sub.setStyleSheet("color:#777;")
        left.addWidget(sub)

        # 1 导入视频
        g1 = self._group("1  导入视频")
        v1 = QtWidgets.QVBoxLayout(g1)
        self.file_lbl = QtWidgets.QLabel("尚未选择视频")
        self.file_lbl.setWordWrap(True)
        self.file_lbl.setStyleSheet("color:#555;")
        pick = QtWidgets.QPushButton("选择视频…")
        pick.clicked.connect(self.pick_video)
        v1.addWidget(self.file_lbl)
        v1.addWidget(pick)
        left.addWidget(g1)

        # 2 目标语言
        g2 = self._group("2  目标语言与密钥")
        f2 = QtWidgets.QGridLayout(g2)
        f2.addWidget(QtWidgets.QLabel("目标语言"), 0, 0)
        self.lang_combo = QtWidgets.QComboBox()
        for code, name in TARGETS:
            self.lang_combo.addItem(f"{name}", code)
        f2.addWidget(self.lang_combo, 0, 1)
        f2.addWidget(QtWidgets.QLabel("DeepL 密钥"), 1, 0)
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.setPlaceholderText("以 :fx 结尾为免费版")
        f2.addWidget(self.key_edit, 1, 1)
        left.addWidget(g2)

        # 3 字幕样式
        g3 = self._group("3  字幕样式")
        v3 = QtWidgets.QVBoxLayout(g3)
        self.style_panel = StylePanel()
        self.style_panel.changed.connect(self.on_style_changed)
        v3.addWidget(self.style_panel)
        left.addWidget(g3)

        # 4 开始处理
        g4 = self._group("4  处理与导出")
        v4 = QtWidgets.QVBoxLayout(g4)
        self.analyze_btn = QtWidgets.QPushButton("开始处理（识别 + 翻译）")
        self.analyze_btn.setStyleSheet(
            "QPushButton{background:#2d6cdf;color:white;font-weight:700;"
            "padding:8px 16px;border-radius:6px;}"
            "QPushButton:disabled{background:#a8c0ea;}")
        self.analyze_btn.clicked.connect(self.start_analyze)
        v4.addWidget(self.analyze_btn)

        outrow = QtWidgets.QHBoxLayout()
        self.cb_mp4 = QtWidgets.QCheckBox("MP4")
        self.cb_mp4.setChecked(True)
        self.cb_srt = QtWidgets.QCheckBox("SRT")
        self.cb_srt.setChecked(True)
        outrow.addWidget(QtWidgets.QLabel("导出："))
        outrow.addWidget(self.cb_mp4)
        outrow.addWidget(self.cb_srt)
        outrow.addStretch(1)
        v4.addLayout(outrow)

        self.export_btn = QtWidgets.QPushButton("导出")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.start_export)
        v4.addWidget(self.export_btn)

        dirrow = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit()
        dirrow.addWidget(self.out_edit, 1)
        d = QtWidgets.QPushButton("输出目录…")
        d.clicked.connect(self.pick_outdir)
        dirrow.addWidget(d)
        v4.addLayout(dirrow)
        left.addWidget(g4)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        left.addWidget(self.progress)
        self.status = QtWidgets.QLabel("就绪")
        self.status.setStyleSheet("color:#555;")
        left.addWidget(self.status)
        left.addStretch(1)

        leftw = QtWidgets.QWidget()
        leftw.setLayout(left)
        leftw.setFixedWidth(430)
        root.addWidget(leftw)

        # ---------- right: preview + results ----------
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)

        g5 = self._group("5  预览（改样式即时生效）")
        v5 = QtWidgets.QVBoxLayout(g5)
        self.preview = PreviewWidget()
        v5.addWidget(self.preview)
        right.addWidget(g5, 3)

        self.tabs = QtWidgets.QTabWidget()
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "时间", "原文", "译文"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        self.tabs.addTab(self.table, "字幕")

        self.qc_view = QtWidgets.QPlainTextEdit()
        self.qc_view.setReadOnly(True)
        self.tabs.addTab(self.qc_view, "质量检查")

        self.logview = QtWidgets.QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.tabs.addTab(self.logview, "日志")
        right.addWidget(self.tabs, 2)

        root.addLayout(right, 1)

    @staticmethod
    def _group(title: str) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox(title)
        g.setStyleSheet(
            "QGroupBox{font-weight:600;border:1px solid #d5d5d5;border-radius:8px;"
            "margin-top:8px;padding:10px 10px 8px 10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        return g

    # -- settings -----------------------------------------------------------
    def _load_settings(self):
        s = self.settings
        self.key_edit.setText(s["api_key"])
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == s["target_lang"]:
                self.lang_combo.setCurrentIndex(i)
                break
        self.out_edit.setText(s["out_dir"] or
                              str(Path.home() / "SubtitleTranslator_Output"))

    def _save_settings(self):
        s = self.settings
        s["api_key"] = self.key_edit.text().strip()
        s["target_lang"] = self.lang_combo.currentData()
        s["out_dir"] = self.out_edit.text().strip()
        s.save()

    # -- inputs -------------------------------------------------------------
    def pick_video(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择视频", "", "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)")
        if not path:
            return
        self.video = path
        self.file_lbl.setText(os.path.basename(path))
        self.result = None
        self.export_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.preview.segments = []
        self.preview.cover_windows = []
        self.preview.open(path)
        self.status.setText("已导入视频，点“开始处理”")

    def pick_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择输出目录", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # -- style --------------------------------------------------------------
    def on_style_changed(self):
        """PRD 十: restyle only repaints — no OCR, no DeepL, no re-render."""
        self.preview.apply_style(self.style_panel.value())

    # -- run ----------------------------------------------------------------
    def _base_cfg(self, outputs) -> JobConfig:
        out_dir = self.out_edit.text().strip() or str(
            Path.home() / "SubtitleTranslator_Output")
        os.makedirs(out_dir, exist_ok=True)
        return JobConfig(
            video_path=self.video,
            target_lang=self.lang_combo.currentData(),
            api_key=self.key_edit.text().strip(),
            outputs=outputs,
            srt_mode="bilingual",
            burn_mode="translation",
            cover_original=True,
            removal_mode="cover",
            style=self.style_panel.value(),
            out_dir=out_dir,
        )

    def start_analyze(self):
        if not self.video:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请先选择视频。")
            return
        if not self.key_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请输入 DeepL 密钥（翻译需要）。")
            return
        self._save_settings()
        self.logview.clear()
        self.table.setRowCount(0)
        self._run(self._base_cfg([]), self.on_analyzed, "识别与翻译中…")

    def start_export(self):
        outs = (["video"] if self.cb_mp4.isChecked() else []) + \
               (["srt"] if self.cb_srt.isChecked() else [])
        if not outs:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请至少选择一种导出格式。")
            return
        self._save_settings()
        self._run(self._base_cfg(outs), self.on_exported, "导出中…")

    def _run(self, cfg, on_done, status):
        self.analyze_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.status.setText(status)
        self.worker = Worker(cfg)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_progress(self, p, msg):
        self.progress.setValue(int(p * 1000))
        self.status.setText(f"{msg}  ({p*100:.0f}%)")

    def on_analyzed(self, result):
        self.result = result
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.fill_table(result.segments)
        self.preview.segments = result.segments
        self.preview.cover_windows = result.cover_windows
        self.preview.apply_style(self.style_panel.value())
        if result.quality:
            self.logview.appendPlainText(result.quality.summary())
        self.show_qc(result)
        self.status.setText("处理完成 — 可在右侧预览，改样式即时生效")

    def on_exported(self, result):
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.progress.setValue(1000)
        for kind, path in result.files.items():
            self.logview.appendPlainText(f"{kind}: {path}")
        self.show_qc(result)
        self.status.setText("导出完成")
        d = self.out_edit.text().strip()
        if d and os.path.isdir(d):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(d))

    def on_failed(self, msg):
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(bool(self.result))
        self.status.setText("处理出错")
        show_error(self, msg)

    # -- results ------------------------------------------------------------
    def fill_table(self, segments):
        self.table.setRowCount(0)
        for s in segments:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate([str(s.index),
                                     f"{_fmt_time(s.start)}–{_fmt_time(s.end)}",
                                     s.text, s.translation]):
                it = QtWidgets.QTableWidgetItem(val)
                it.setToolTip(val)
                it.setTextAlignment(QtCore.Qt.AlignTop |
                                    (QtCore.Qt.AlignHCenter if c < 2
                                     else QtCore.Qt.AlignLeft))
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()

    def on_row_selected(self):
        """Jump the preview to the selected caption."""
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self.result:
            return
        i = rows[0].row()
        if 0 <= i < len(self.result.segments):
            seg = self.result.segments[i]
            self.preview.seek_frame(int((seg.start + seg.end) / 2 *
                                        self.preview._fps))

    def show_qc(self, result):
        if not result.qc:
            return
        lines = [result.qc.summary(), ""]
        lines += [str(f) for f in result.qc.findings]
        self.qc_view.setPlainText("\n".join(lines))
        if result.qc.errors:
            self.tabs.setCurrentIndex(1)

    def closeEvent(self, ev):
        self._save_settings()
        self.preview.close_video()
        super().closeEvent(ev)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
