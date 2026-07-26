@echo off
REM ============================================================
REM  Build SubtitleTranslator.exe on Windows
REM  Prereqs: Python 3.10+, and (recommended) tesseract + ffmpeg on PATH
REM ============================================================
setlocal
cd /d "%~dp0\.."

echo [1/4] Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
REM Optional high-accuracy OCR:
REM pip install paddleocr paddlepaddle

echo [3/4] Building with PyInstaller...
pyinstaller build\SubtitleTranslator.spec --noconfirm --distpath dist --workpath build\_work

echo [4/4] Done. App is in: dist\SubtitleTranslator\SubtitleTranslator.exe
pause
