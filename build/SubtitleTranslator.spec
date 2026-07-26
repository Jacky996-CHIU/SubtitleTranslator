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

import glob

binaries = []
def _bundle(tool, dest="."):
    p = shutil.which(tool)
    if not p:
        return None
    binaries.append((p, dest))
    # On Windows the tool's shared libraries (e.g. Tesseract's leptonica DLLs)
    # sit next to the .exe and must ship with it. PyInstaller traces most, but
    # grab the siblings explicitly to be safe.
    if os.name == "nt":
        for dll in glob.glob(os.path.join(os.path.dirname(p), "*.dll")):
            binaries.append((dll, dest))
    return p

# Best-effort bundling of external tools.
_bundle("ffmpeg")
_bundle("ffprobe")
tess = _bundle("tesseract")

# The imageio-ffmpeg wheel ships a static ffmpeg built WITH libass, which the
# app needs to burn subtitles (Homebrew/distro ffmpeg is sometimes built without
# it and then has no 'subtitles' filter at all). Ship it inside the package so
# imageio_ffmpeg.get_ffmpeg_exe() resolves it at runtime.
try:
    import imageio_ffmpeg
    _iio = imageio_ffmpeg.get_ffmpeg_exe()
    if _iio and os.path.isfile(_iio):
        binaries.append((_iio, os.path.join("imageio_ffmpeg", "binaries")))
except Exception:
    pass

# Tesseract language data. Prefer TESSDATA_PREFIX; otherwise infer from the
# tesseract install layout so the packaged app is self-contained.
datas = []
def _find_tessdata():
    env = os.environ.get("TESSDATA_PREFIX")
    if env and os.path.isdir(env):
        return env
    if tess:
        base = os.path.dirname(os.path.dirname(tess))  # <prefix>/bin/tesseract
        for cand in (os.path.join(base, "share", "tessdata"),
                     os.path.join(os.path.dirname(tess), "tessdata")):
            if os.path.isdir(cand):
                return cand
    return None
tessdata = _find_tessdata()
if tessdata:
    datas.append((tessdata, "tessdata"))

# The GUI modules sit next to app.py and are imported by bare name.
hiddenimports = (collect_submodules("subtrans")
                 + ["imageio_ffmpeg", "preview", "style_panel"])

a = Analysis(
    ["../gui/app.py"],
    pathex=[ROOT, os.path.join(ROOT, "gui"), os.path.dirname(ROOT)],
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
