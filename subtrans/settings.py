"""Persistent user settings (API key, last folders, preferences)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    import platform
    sysname = platform.system()
    if sysname == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sysname == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "SubtitleTranslator"
    d.mkdir(parents=True, exist_ok=True)
    return d


_DEFAULTS = {
    "api_key": "",
    "target_lang": "ZH",
    "source_lang": "EN",
    "engine": "auto",
    "outputs": ["srt", "video", "docx"],
    # ---- 四个常调开关 (four common knobs) ---------------------------------
    "srt_mode": "bilingual",       # SRT: original | translation | bilingual
    "burn_mode": "translation",    # 压制进视频: original | translation | bilingual
    "cover_original": True,        # 是否遮盖原字幕
    "burn_font": "",               # 压制字体; "" = 自动(西文 Arial / 中日韩系统字体)
    "burn_font_size": 0,           # 压制字号 px; 0 = 按视频高度自动
    # ----------------------------------------------------------------------
    "sample_fps": 4.0,
    "out_dir": str(Path.home() / "SubtitleTranslator_Output"),
}


class Settings:
    def __init__(self):
        self.path = config_dir() / "settings.json"
        self.data = dict(_DEFAULTS)
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data.get(k, _DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v
