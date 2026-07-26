"""
Output writers: SRT subtitles, burned-in (hardcoded) video, and Word document.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional

from .extractor import Segment


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #
def _fmt_ts(seconds: float, sep: str = ",") -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


# --------------------------------------------------------------------------- #
# SRT
# --------------------------------------------------------------------------- #
def write_srt(
    segments: List[Segment],
    path: str,
    mode: str = "translation",   # 'original' | 'translation' | 'bilingual'
) -> str:
    lines = []
    for s in segments:
        if mode == "original":
            body = s.text
        elif mode == "bilingual":
            body = (s.translation + "\n" + s.text).strip()
        else:
            body = s.translation or s.text
        lines.append(str(s.index))
        lines.append(f"{_fmt_ts(s.start)} --> {_fmt_ts(s.end)}")
        lines.append(body.replace("\n", "\n"))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# --------------------------------------------------------------------------- #
# ASS (for nicely styled burn-in that mimics the original bold-white caption)
# --------------------------------------------------------------------------- #
def _ass_ts(seconds: float) -> str:
    return _fmt_ts(seconds, sep=".")[:-1]  # ASS uses H:MM:SS.cc (centiseconds)


def write_ass(
    segments: List[Segment],
    path: str,
    mode: str = "translation",
    font: str = "Arial",
    font_size: int = 22,
    play_res_x: int = 640,
    play_res_y: int = 360,
    primary: str = "&H00FFFFFF",   # white (AABBGGRR)
    outline: str = "&H00000000",   # black
    bold: int = -1,                # -1 = true
    alignment: int = 1,            # 1=bottom-left (matches source captions)
    margin_l: int = 24,
    margin_v: int = 28,
    border_style: int = 1,         # 1=outline+shadow, 3=opaque box (masks original)
    box_color: str = "&H00101010", # near-black box (used when border_style=3)
    outline_w: int = 2,
) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{font_size},{primary},{outline},{box_color},{bold},0,0,0,100,100,0,0,{border_style},{outline_w},1,{alignment},{margin_l},20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for s in segments:
        if mode == "original":
            body = s.text
        elif mode == "bilingual":
            body = (s.translation + "\n" + s.text).strip()
        else:
            body = s.translation or s.text
        body = body.replace("\n", "\\N")
        ev.append(
            f"Dialogue: 0,{_ass_ts(s.start)},{_ass_ts(s.end)},Caption,,0,0,0,,{body}"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(ev) + "\n")
    return path


# --------------------------------------------------------------------------- #
# Burn subtitles into video (ffmpeg)
# --------------------------------------------------------------------------- #
def ffmpeg_path() -> str:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg") or "ffmpeg"


def _probe_dims(video_in: str):
    try:
        out = subprocess.check_output([
            ffmpeg_path().replace("ffmpeg", "ffprobe"),
            "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", video_in,
        ], text=True).strip()
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 640, 360


def _cover_filters(segments: List[Segment], w: int, h: int, pad: int = 6) -> str:
    """drawbox filters that mask each original caption for its time range."""
    parts = []
    for s in segments:
        if not s.orig_box:
            continue
        x, y, bw, bh = s.orig_box
        x = max(0, x - pad); y = max(0, y - pad)
        bw = min(w - x, bw + 2 * pad); bh = min(h - y, bh + 2 * pad)
        st, en = s.start, s.end
        parts.append(
            f"drawbox=x={x}:y={y}:w={bw}:h={bh}:color=black@1.0:t=fill:"
            f"enable='between(t,{st:.2f},{en:.2f})'"
        )
    return ",".join(parts)


def burn_video(
    video_in: str,
    segments: List[Segment],
    video_out: str,
    workdir: str,
    mode: str = "translation",
    font: str = "Arial",
    font_size: Optional[int] = None,
    fonts_dir: Optional[str] = None,
    cover_original: bool = True,
    progress_cb=None,
) -> str:
    """Render a new MP4 with the (translated) captions burned in.

    When ``cover_original`` is True, the original burned-in caption is masked
    with a fill box (using the detected bounding box) before the translated
    caption is drawn, so the result shows only the translation.
    """
    w, h = _probe_dims(video_in)
    fs = font_size or max(18, int(h * 0.062))
    ass_file = os.path.join(workdir, "burn.ass")
    # When covering the original we align to bottom-left over the masked area.
    write_ass(segments, ass_file, mode=mode, font=font, font_size=fs,
              play_res_x=w, play_res_y=h)

    ass_esc = ass_file.replace("\\", "/").replace(":", "\\:")
    sub = f"subtitles='{ass_esc}'"
    if fonts_dir:
        sub = f"subtitles='{ass_esc}':fontsdir='{fonts_dir}'"

    vf = sub
    if cover_original:
        cover = _cover_filters(segments, w, h)
        if cover:
            vf = cover + "," + sub

    cmd = [
        ffmpeg_path(), "-y", "-i", video_in,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy", video_out,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg burn failed:\n" + proc.stderr[-2000:])
    return video_out


# --------------------------------------------------------------------------- #
# Word document
# --------------------------------------------------------------------------- #
def write_docx(
    segments: List[Segment],
    path: str,
    title: str = "字幕翻译 / Subtitle Translation",
    source_lang: str = "EN",
    target_lang: str = "",
    video_name: str = "",
) -> str:
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    doc.add_heading(title, level=0)
    meta = doc.add_paragraph()
    meta.add_run(
        f"视频 / Video: {video_name}\n"
        f"源语言 / Source: {source_lang}    目标语言 / Target: {target_lang}\n"
        f"字幕条数 / Segments: {len(segments)}"
    ).font.size = Pt(10)

    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for c, t in zip(hdr, ["#", "时间 / Time", "原文 / Original", "译文 / Translation"]):
        run = c.paragraphs[0].add_run(t)
        run.bold = True

    for s in segments:
        row = table.add_row().cells
        row[0].text = str(s.index)
        row[1].text = f"{_fmt_ts(s.start)}\n{_fmt_ts(s.end)}"
        row[2].text = s.text.replace("\n", " ")
        row[3].text = (s.translation or "").replace("\n", " ")

    doc.save(path)
    return path
