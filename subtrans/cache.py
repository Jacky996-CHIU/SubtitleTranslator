"""
On-disk cache for OCR results and translations (PRD 十三).

Changing subtitle style must never re-run OCR or call DeepL again, so both the
recognized captions and the translated lines are cached, keyed by everything
that could change the result.

Layout::

    <cache_dir>/ocr/<key>.json          recognized captions for one video
    <cache_dir>/translate/<key>.json    {source_text: translation} per language
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from typing import Dict, List, Optional


def default_cache_dir() -> str:
    """Per-user cache location, override with ``SUBTRANS_CACHE_DIR``."""
    env = os.environ.get("SUBTRANS_CACHE_DIR")
    if env:
        return env
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "SubtitleTranslator", "cache")
    if os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        return os.path.join(home, "Library", "Caches", "SubtitleTranslator")
    return os.path.join(home, ".cache", "subtitletranslator")


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def video_fingerprint(path: str) -> str:
    """Identify a video by path + size + mtime — no need to hash gigabytes."""
    try:
        st = os.stat(path)
        return _hash(os.path.abspath(path), st.st_size, int(st.st_mtime))
    except OSError:
        return _hash(os.path.abspath(path))


class Cache:
    def __init__(self, cache_dir: Optional[str] = None, enabled: bool = True):
        self.dir = cache_dir or default_cache_dir()
        self.enabled = enabled

    # -- generic ------------------------------------------------------------
    def _path(self, kind: str, key: str) -> str:
        d = os.path.join(self.dir, kind)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{key}.json")

    def _read(self, kind: str, key: str):
        if not self.enabled:
            return None
        try:
            with open(self._path(kind, key), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, kind: str, key: str, payload) -> None:
        if not self.enabled:
            return
        try:
            tmp = self._path(kind, key) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self._path(kind, key))
        except OSError:
            pass

    # -- OCR ----------------------------------------------------------------
    def ocr_key(self, video_path: str, engine: str, sample_fps: float,
                extra: str = "") -> str:
        return _hash(video_fingerprint(video_path), engine, sample_fps, extra)

    def get_ocr(self, key: str) -> Optional[dict]:
        data = self._read("ocr", key)
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            return data
        return None

    def put_ocr(self, key: str, segments, cover_windows=None) -> None:
        self._write("ocr", key, {
            "version": 2,
            "segments": [asdict(s) for s in segments],
            "cover_windows": [[a, b, list(box)]
                              for (a, b, box) in (cover_windows or [])],
        })

    # -- translation --------------------------------------------------------
    def translate_key(self, target_lang: str, source_lang: str) -> str:
        return _hash("deepl", source_lang, target_lang)

    def get_translations(self, key: str) -> Dict[str, str]:
        data = self._read("translate", key)
        return data if isinstance(data, dict) else {}

    def put_translations(self, key: str, mapping: Dict[str, str]) -> None:
        self._write("translate", key, mapping)

    def clear(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)
