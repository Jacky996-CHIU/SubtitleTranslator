# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — builds a single-window desktop app for the host OS.

Run on EACH target OS to produce that platform's binary:
    Windows :  pyinstaller build/SubtitleTranslator.spec      -> dist/SubtitleTranslator/SubtitleTranslator.exe
    macOS   :  pyinstaller build/SubtitleTranslator.spec      -> dist/SubtitleTranslator.app

If tesseract / ffmpeg binaries are found on PATH they are bundled next to the
app so end users don't have to install anything. Otherwise the app falls back
to the system-installed copies at runtime.
"""

import os
import shutil
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = os.path.abspath(os.getcwd())

binaries = []
def _bundle(tool, dest):
    p = shutil.which(tool)
    if p:
        binaries.append((p, dest))

# Best-effort bundling of external tools.
_bundle("ffmpeg", ".")
_bundle("ffprobe", ".")
_bundle("tesseract", ".")

# Tesseract language data (eng) if discoverable.
datas = []
tessdata = os.environ.get("TESSDATA_PREFIX")
if tessdata and os.path.isdir(tessdata):
    datas.append((tessdata, "tessdata"))

hiddenimports = collect_submodules("subtrans")

a = Analysis(
    ["../gui/app.py"],
    pathex=[ROOT, os.path.dirname(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SubtitleTranslator",
    debug=False,
    strip=False,
    upx=False,
    console=False,               # windowed GUI app
    icon=os.path.join(ROOT, "assets", "icon.ico") if os.path.exists(
        os.path.join(ROOT, "assets", "icon.ico")) else None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="SubtitleTranslator",
)

app = BUNDLE(
    coll,
    name="SubtitleTranslator.app",
    icon=os.path.join(ROOT, "assets", "icon.icns") if os.path.exists(
        os.path.join(ROOT, "assets", "icon.icns")) else None,
    bundle_identifier="com.subtitletranslator.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "1.0.0",
    },
)
