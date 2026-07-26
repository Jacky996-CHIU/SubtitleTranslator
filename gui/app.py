"""
SubtitleTranslator — cross-platform desktop GUI (PySide6).

Recognizes burned-in captions in finished videos, translates them with DeepL,
and exports bilingual SRT, a re-burned MP4, and a Word document.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Allow running from source tree.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from subtrans.settings import Settings  # noqa: E402
from subtrans.pipeline import JobConfig, run_job  # noqa: E402


APP_NAME = "字幕翻译 · SubtitleTranslator"

# Static fallback list so the dropdown is populated before a key is verified.
# The live list is refreshed from DeepL when a valid key is present.
FALLBACK_TARGETS = [
    ("ZH", "中文 Chinese (simplified)"), ("ZH-HANT", "中文繁體 Chinese (traditional)"),
    ("EN-US", "English (American)"), ("EN-GB", "English (British)"),
    ("JA", "日本語 Japanese"), ("KO", "한국어 Korean"),
    ("DE", "Deutsch German"), ("FR", "Français French"),
    ("ES", "Español Spanish"), ("IT", "Italiano Italian"),
    ("PT-BR", "Português (BR)"), ("PT-PT", "Português (PT)"),
    ("RU", "Русский Russian"), ("NL", "Nederlands Dutch"),
    ("PL", "Polski Polish"), ("TR", "Türkçe Turkish"),
    ("AR", "العربية Arabic"), ("ID", "Indonesian"), ("UK", "Ukrainian"),
    ("CS", "Czech"), ("DA", "Danish"), ("FI", "Finnish"), ("EL", "Greek"),
    ("HU", "Hungarian"), ("NB", "Norwegian"), ("RO", "Romanian"),
    ("SK", "Slovak"), ("SV", "Swedish"), ("BG", "Bulgarian"),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{int(m):02d}:{s:04.1f}"
    return f"{int(m):02d}:{s:04.1f}"


def _show_error_dialog(parent, msg: str):
    """A bounded, scrollable, always-closable error dialog.

    The old code passed the full ffmpeg stderr into QMessageBox, which grew the
    dialog past the screen so its button was unreachable. This keeps a fixed
    size with the details in a scroll area.
    """
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(APP_NAME + " — 出错 / Error")
    dlg.resize(680, 440)
    lay = QtWidgets.QVBoxLayout(dlg)

    head = QtWidgets.QLabel("处理时出错了。详情如下（可滚动、可复制）:")
    head.setStyleSheet("font-weight:700;")
    lay.addWidget(head)

    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(msg)
    box.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    box.setStyleSheet("font-family:Menlo,Consolas,monospace;font-size:12px;")
    lay.addWidget(box, 1)

    btns = QtWidgets.QHBoxLayout()
    copy_btn = QtWidgets.QPushButton("复制 / Copy")
    copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(msg))
    close_btn = QtWidgets.QPushButton("关闭 / Close")
    close_btn.setDefault(True)
    close_btn.clicked.connect(dlg.accept)
    btns.addWidget(copy_btn)
    btns.addStretch(1)
    btns.addWidget(close_btn)
    lay.addLayout(btns)

    dlg.exec()


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #
class JobWorker(QtCore.QThread):
    progress = QtCore.Signal(float, str)
    log = QtCore.Signal(str)
    file_done = QtCore.Signal(str, str)       # kind, path
    captions = QtCore.Signal(str, list)       # video name, [(idx,start,end,orig,trans)]
    video_done = QtCore.Signal(str)           # per-video finished
    error = QtCore.Signal(str)
    finished_all = QtCore.Signal()

    def __init__(self, videos, base_cfg: dict, api_key: str):
        super().__init__()
        self.videos = videos
        self.base = base_cfg
        self.api_key = api_key
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            n = len(self.videos)
            for i, vid in enumerate(self.videos):
                if self._stop:
                    break
                self.log.emit(f"▶ [{i+1}/{n}] {os.path.basename(vid)}")
                cfg = JobConfig(
                    video_path=vid,
                    target_lang=self.base["target_lang"],
                    source_lang=self.base["source_lang"],
                    api_key=self.api_key,
                    ocr_engine=self._resolve_engine(),
                    outputs=self.base["outputs"],
                    srt_mode=self.base["srt_mode"],
                    cover_original=self.base["cover_original"],
                    out_dir=self.base["out_dir"],
                    sample_fps=float(self.base["sample_fps"]),
                )

                def pcb(p, m, i=i):
                    self.progress.emit((i + p) / n, m)

                result = run_job(cfg, progress_cb=pcb)
                rows = [
                    (s.index, s.start, s.end, s.text, s.translation)
                    for s in result.segments
                ]
                self.captions.emit(os.path.basename(vid), rows)
                for kind, path in result.files.items():
                    self.file_done.emit(kind, path)
                self.log.emit(
                    f"✓ 完成 {os.path.basename(vid)} — 识别 {len(result.segments)} 条字幕"
                )
                self.video_done.emit(vid)
            self.finished_all.emit()
        except Exception as e:
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")

    def _resolve_engine(self):
        eng = self.base.get("engine", "auto")
        if eng == "auto":
            try:
                import paddleocr  # noqa: F401
                return "paddleocr"
            except Exception:
                return "tesseract"
        return eng


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.videos: list[str] = []
        self.worker: JobWorker | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(920, 660)
        self._build_ui()
        self._load_settings()

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel(APP_NAME)
        title.setStyleSheet("font-size:20px;font-weight:700;")
        root.addWidget(title)
        sub = QtWidgets.QLabel(
            "识别视频里烧录的字幕 → DeepL 翻译 → 导出 SRT / 压制视频 / Word\n"
            "Recognize burned-in captions → translate with DeepL → export SRT / video / Word"
        )
        sub.setStyleSheet("color:#666;")
        root.addWidget(sub)

        # --- Videos drop zone
        self.drop = DropList(self)
        self.drop.filesDropped.connect(self.add_videos)
        root.addWidget(self.drop, 1)

        vbtns = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("添加视频 / Add videos")
        add_btn.clicked.connect(self.pick_videos)
        clr_btn = QtWidgets.QPushButton("清空 / Clear")
        clr_btn.clicked.connect(self.clear_videos)
        vbtns.addWidget(add_btn)
        vbtns.addWidget(clr_btn)
        vbtns.addStretch(1)
        root.addLayout(vbtns)

        # --- Settings grid
        form = QtWidgets.QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        r = 0

        form.addWidget(QtWidgets.QLabel("DeepL API 密钥:"), r, 0)
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.setPlaceholderText("xxxxxxxx-xxxx-...  (:fx = 免费版)")
        form.addWidget(self.key_edit, r, 1)
        self.verify_btn = QtWidgets.QPushButton("验证密钥 / 刷新语言")
        self.verify_btn.clicked.connect(self.verify_key)
        form.addWidget(self.verify_btn, r, 2)
        r += 1

        form.addWidget(QtWidgets.QLabel("目标语言 / Target:"), r, 0)
        self.lang_combo = QtWidgets.QComboBox()
        for code, name in FALLBACK_TARGETS:
            self.lang_combo.addItem(f"{name}  [{code}]", code)
        form.addWidget(self.lang_combo, r, 1)
        self.usage_lbl = QtWidgets.QLabel("")
        self.usage_lbl.setStyleSheet("color:#888;")
        form.addWidget(self.usage_lbl, r, 2)
        r += 1

        form.addWidget(QtWidgets.QLabel("识别引擎 / OCR:"), r, 0)
        self.engine_combo = QtWidgets.QComboBox()
        self.engine_combo.addItem("自动 (有 PaddleOCR 则用，最高精度)", "auto")
        self.engine_combo.addItem("Tesseract (轻量，内置)", "tesseract")
        self.engine_combo.addItem("PaddleOCR (最高精度，需安装)", "paddleocr")
        form.addWidget(self.engine_combo, r, 1)
        r += 1

        form.addWidget(QtWidgets.QLabel("输出 / Outputs:"), r, 0)
        obox = QtWidgets.QHBoxLayout()
        self.cb_srt = QtWidgets.QCheckBox("SRT 字幕")
        self.cb_video = QtWidgets.QCheckBox("压制视频")
        self.cb_docx = QtWidgets.QCheckBox("Word 文档")
        for cb in (self.cb_srt, self.cb_video, self.cb_docx):
            cb.setChecked(True)
            obox.addWidget(cb)
        obox.addStretch(1)
        w = QtWidgets.QWidget(); w.setLayout(obox)
        form.addWidget(w, r, 1, 1, 2)
        r += 1

        form.addWidget(QtWidgets.QLabel("SRT 样式:"), r, 0)
        self.srt_combo = QtWidgets.QComboBox()
        self.srt_combo.addItem("双语 (译文+原文) / bilingual", "bilingual")
        self.srt_combo.addItem("仅译文 / translation", "translation")
        self.srt_combo.addItem("仅原文 / original", "original")
        form.addWidget(self.srt_combo, r, 1)
        self.cb_cover = QtWidgets.QCheckBox("压制时遮盖原字幕 / cover original")
        self.cb_cover.setChecked(True)
        form.addWidget(self.cb_cover, r, 2)
        r += 1

        form.addWidget(QtWidgets.QLabel("输出目录 / Folder:"), r, 0)
        self.out_edit = QtWidgets.QLineEdit()
        form.addWidget(self.out_edit, r, 1)
        out_btn = QtWidgets.QPushButton("选择…")
        out_btn.clicked.connect(self.pick_outdir)
        form.addWidget(out_btn, r, 2)
        r += 1

        root.addLayout(form)

        # --- Run row
        runrow = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("开始 / Start")
        self.run_btn.setStyleSheet(
            "QPushButton{background:#2d6cdf;color:white;font-weight:700;"
            "padding:8px 22px;border-radius:6px;}"
            "QPushButton:disabled{background:#9bb6e8;}")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = QtWidgets.QPushButton("停止")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.open_btn = QtWidgets.QPushButton("打开输出目录")
        self.open_btn.clicked.connect(self.open_outdir)
        runrow.addWidget(self.run_btn)
        runrow.addWidget(self.cancel_btn)
        runrow.addStretch(1)
        runrow.addWidget(self.open_btn)
        root.addLayout(runrow)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        root.addWidget(self.progress)

        self.status = QtWidgets.QLabel("就绪 / Ready")
        self.status.setStyleSheet("color:#555;")
        root.addWidget(self.status)

        # --- Results (captions table) + log, in tabs
        self.tabs = QtWidgets.QTabWidget()

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["#", "时间 Time", "原文 Original", "译文 Translation"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.tabs.addTab(self.table, "识别字幕 / Captions")

        self.logview = QtWidgets.QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.tabs.addTab(self.logview, "日志 / Log")

        root.addWidget(self.tabs, 2)

    # -- settings load/save -------------------------------------------------
    def _load_settings(self):
        s = self.settings
        self.key_edit.setText(s["api_key"])
        self._select_combo(self.lang_combo, s["target_lang"])
        self._select_combo(self.engine_combo, s["engine"])
        outs = s["outputs"]
        self.cb_srt.setChecked("srt" in outs)
        self.cb_video.setChecked("video" in outs)
        self.cb_docx.setChecked("docx" in outs)
        self._select_combo(self.srt_combo, s["srt_mode"])
        self.cb_cover.setChecked(bool(s["cover_original"]))
        self.out_edit.setText(s["out_dir"])

    def _save_settings(self):
        s = self.settings
        s["api_key"] = self.key_edit.text().strip()
        s["target_lang"] = self.lang_combo.currentData()
        s["engine"] = self.engine_combo.currentData()
        s["outputs"] = self._selected_outputs()
        s["srt_mode"] = self.srt_combo.currentData()
        s["cover_original"] = self.cb_cover.isChecked()
        s["out_dir"] = self.out_edit.text().strip()
        s.save()

    @staticmethod
    def _select_combo(combo, data):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return

    def _selected_outputs(self):
        outs = []
        if self.cb_srt.isChecked():
            outs.append("srt")
        if self.cb_video.isChecked():
            outs.append("video")
        if self.cb_docx.isChecked():
            outs.append("docx")
        return outs

    # -- video list ---------------------------------------------------------
    def pick_videos(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择视频", "", "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)")
        self.add_videos(files)

    def add_videos(self, files):
        for f in files:
            if f and f not in self.videos:
                self.videos.append(f)
        self.drop.set_items(self.videos)

    def clear_videos(self):
        self.videos = []
        self.drop.set_items(self.videos)

    def pick_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择输出目录",
                                                       self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def open_outdir(self):
        d = self.out_edit.text().strip()
        if d and os.path.isdir(d):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(d))

    # -- DeepL key verification --------------------------------------------
    def verify_key(self):
        key = self.key_edit.text().strip()
        if not key:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请先输入 DeepL API 密钥。")
            return
        try:
            from subtrans.translate import DeepLTranslator
            t = DeepLTranslator(key)
            langs = t.target_languages()
            cur = self.lang_combo.currentData()
            self.lang_combo.clear()
            for l in langs:
                self.lang_combo.addItem(f"{l.name}  [{l.code}]", l.code)
            self._select_combo(self.lang_combo, cur)
            try:
                u = t.usage()
                if u.character.valid:
                    self.usage_lbl.setText(
                        f"用量 {u.character.count:,}/{u.character.limit:,} 字符")
            except Exception:
                pass
            QtWidgets.QMessageBox.information(
                self, APP_NAME, f"密钥有效，已载入 {len(langs)} 种目标语言。")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, APP_NAME, f"密钥验证失败:\n{e}")

    # -- run ----------------------------------------------------------------
    def start(self):
        if not self.videos:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请先添加视频。")
            return
        outs = self._selected_outputs()
        if not outs:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "请至少选择一种输出。")
            return
        key = self.key_edit.text().strip()
        if not key:
            QtWidgets.QMessageBox.warning(
                self, APP_NAME, "请输入 DeepL API 密钥（翻译需要）。")
            return
        out_dir = self.out_edit.text().strip() or str(Path.home() / "SubtitleTranslator_Output")
        os.makedirs(out_dir, exist_ok=True)
        self._save_settings()

        base = {
            "target_lang": self.lang_combo.currentData(),
            "source_lang": self.settings["source_lang"],
            "engine": self.engine_combo.currentData(),
            "outputs": outs,
            "srt_mode": self.srt_combo.currentData(),
            "cover_original": self.cb_cover.isChecked(),
            "out_dir": out_dir,
            "sample_fps": self.settings["sample_fps"],
        }
        self.logview.clear()
        self.table.setRowCount(0)
        self.tabs.setCurrentIndex(0)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.worker = JobWorker(list(self.videos), base, key)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.on_log)
        self.worker.file_done.connect(self.on_file_done)
        self.worker.captions.connect(self.on_captions)
        self.worker.error.connect(self.on_error)
        self.worker.finished_all.connect(self.on_finished)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("正在停止…")

    def on_progress(self, p, msg):
        self.progress.setValue(int(p * 1000))
        self.status.setText(f"{msg}  ({p*100:.0f}%)")

    def on_log(self, msg):
        self.logview.appendPlainText(msg)

    def on_file_done(self, kind, path):
        self.logview.appendPlainText(f"    → {kind}: {path}")

    def on_captions(self, video_name, rows):
        """Fill the results table with recognized text + translation."""
        if self.table.rowCount() and len(self.videos) > 1:
            self._add_section_row(video_name)
        for idx, start, end, orig, trans in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            cells = [
                str(idx),
                f"{_fmt_time(start)}–{_fmt_time(end)}",
                orig,
                trans,
            ]
            for c, val in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(val)
                it.setToolTip(val)
                if c in (0, 1):
                    it.setTextAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter)
                else:
                    it.setTextAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()
        self.tabs.setCurrentIndex(0)

    def _add_section_row(self, video_name):
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QtWidgets.QTableWidgetItem(f"▼ {video_name}")
        f = it.font(); f.setBold(True); it.setFont(f)
        it.setBackground(QtGui.QBrush(QtGui.QColor("#eef2fb")))
        self.table.setItem(r, 0, it)
        self.table.setSpan(r, 0, 1, 4)

    def on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText("出错 / Error")
        _show_error_dialog(self, msg)

    def on_finished(self):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(1000)
        self.status.setText("全部完成 / All done")
        self.open_outdir()

    def closeEvent(self, ev):
        self._save_settings()
        super().closeEvent(ev)


class DropList(QtWidgets.QListWidget):
    filesDropped = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self._placeholder()

    def _placeholder(self):
        self.clear()
        it = QtWidgets.QListWidgetItem("拖拽视频到这里，或点“添加视频” / Drop videos here")
        it.setForeground(QtGui.QBrush(QtGui.QColor("#999")))
        it.setFlags(QtCore.Qt.NoItemFlags)
        self.addItem(it)

    def set_items(self, files):
        self.clear()
        if not files:
            self._placeholder()
            return
        for f in files:
            self.addItem(os.path.basename(f))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        exts = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
        files = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(exts)]
        if files:
            self.filesDropped.emit(files)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("SubtitleTranslator")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
