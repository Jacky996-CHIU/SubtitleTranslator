"""
Locate external tools (ffmpeg / ffprobe / tesseract) and their data when the app
is frozen by PyInstaller, so the packaged desktop app is fully self-contained and
"just works" without the user installing anything.

In a normal source checkout (not frozen) every helper returns ``None`` and the
callers fall back to the system ``PATH`` exactly as before.
"""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle (.app / onedir .exe)."""
    return bool(getattr(sys, "frozen", False))


def _candidate_dirs() -> list[str]:
    """Directories where PyInstaller may have placed bundled resources."""
    dirs: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    dirs.append(exe_dir)
    # macOS .app layout: exe lives in Contents/MacOS, resources may sit in
    # sibling Frameworks/ or Resources/ folders.
    dirs.append(os.path.join(exe_dir, os.pardir, "Frameworks"))
    dirs.append(os.path.join(exe_dir, os.pardir, "Resources"))
    seen: set[str] = set()
    out: list[str] = []
    for d in dirs:
        rp = os.path.realpath(d)
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def _exe_name(tool: str) -> str:
    return tool + (".exe" if os.name == "nt" else "")


def find_tool(tool: str) -> str | None:
    """Absolute path to a bundled ``tool`` binary, or ``None`` if not bundled."""
    if not is_frozen():
        return None
    name = _exe_name(tool)
    for d in _candidate_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def tessdata_dir() -> str | None:
    """Bundled ``tessdata`` directory (contains ``*.traineddata``), or ``None``."""
    if not is_frozen():
        return None
    for d in _candidate_dirs():
        p = os.path.join(d, "tessdata")
        if os.path.isdir(p):
            return p
    return None
