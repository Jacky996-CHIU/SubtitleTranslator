"""
GPU encoder detection (PRD 十五 GPU 自动检测).

Picks the fastest H.264 encoder the local ffmpeg can actually use:

* macOS (Intel and Apple Silicon) — VideoToolbox
* Windows — NVIDIA NVENC, Intel Quick Sync, AMD AMF
* otherwise — software libx264

Availability is confirmed by a one-frame trial encode, because ffmpeg lists
encoders it was merely *built* with, which fails at runtime without the matching
hardware or driver.
"""

from __future__ import annotations

import platform
import subprocess
from typing import List, Optional

_CACHE: dict = {}

# Preference order per platform, best first.
_CANDIDATES = {
    "Darwin": ["h264_videotoolbox"],
    "Windows": ["h264_nvenc", "h264_qsv", "h264_amf"],
    "Linux": ["h264_nvenc", "h264_vaapi", "h264_qsv"],
}


def _listed_encoders(ffmpeg: str) -> List[str]:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return []
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.append(parts[1])
    return names


def _trial_encode(ffmpeg: str, enc: str) -> bool:
    """Encode a couple of synthetic frames to prove the encoder really works."""
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-y",
           "-f", "lavfi", "-i", "color=c=black:size=320x240:rate=25:duration=0.2",
           "-c:v", enc, "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60).returncode == 0
    except Exception:
        return False


def detect_encoder(ffmpeg: str, allow_gpu: bool = True) -> str:
    """Best available H.264 encoder name for this machine."""
    key = (ffmpeg, allow_gpu)
    if key in _CACHE:
        return _CACHE[key]
    chosen = "libx264"
    if allow_gpu:
        listed = set(_listed_encoders(ffmpeg))
        for enc in _CANDIDATES.get(platform.system(), []):
            if enc in listed and _trial_encode(ffmpeg, enc):
                chosen = enc
                break
    _CACHE[key] = chosen
    return chosen


def describe(encoder: str) -> str:
    return {
        "libx264": "软件编码 (libx264)",
        "h264_videotoolbox": "硬件加速 · Apple VideoToolbox",
        "h264_nvenc": "硬件加速 · NVIDIA NVENC",
        "h264_qsv": "硬件加速 · Intel Quick Sync",
        "h264_amf": "硬件加速 · AMD AMF",
        "h264_vaapi": "硬件加速 · VAAPI",
    }.get(encoder, encoder)
