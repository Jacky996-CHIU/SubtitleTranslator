#!/usr/bin/env bash
# ============================================================
#  Build SubtitleTranslator.app on macOS (Intel or Apple Silicon)
#  Prereqs: Python 3.10+, and (recommended) tesseract + ffmpeg:
#      brew install tesseract ffmpeg
# ============================================================
set -e
cd "$(dirname "$0")/.."

echo "[1/4] Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "[2/4] Installing dependencies..."
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
# Optional high-accuracy OCR:
# pip install paddleocr paddlepaddle

# Help the spec bundle Tesseract language data.
if command -v brew >/dev/null 2>&1; then
  export TESSDATA_PREFIX="$(brew --prefix)/share/tessdata"
fi

echo "[3/4] Building with PyInstaller..."
pyinstaller build/SubtitleTranslator.spec --noconfirm --distpath dist --workpath build/_work

echo "[4/4] Done. App bundle: dist/SubtitleTranslator.app"
echo "To make a DMG:  hdiutil create -volname SubtitleTranslator -srcfolder dist/SubtitleTranslator.app -ov -format UDZO dist/SubtitleTranslator.dmg"
