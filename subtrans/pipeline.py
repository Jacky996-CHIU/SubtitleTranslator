"""
End-to-end orchestration: extract -> translate -> write outputs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .extractor import SubtitleExtractor, Segment, ExtractConfig
from .ocr_engine import OCRConfig, build_engine
from . import outputs


# Fonts known to cover CJK, so burned-in Chinese/Japanese/Korean render.
CJK_TARGETS = {"ZH", "ZH-HANS", "ZH-HANT", "JA", "KO"}


@dataclass
class JobConfig:
    video_path: str
    target_lang: str
    api_key: str = ""
    source_lang: str = "EN"
    ocr_engine: str = "tesseract"          # or 'paddleocr'
    outputs: List[str] = field(default_factory=lambda: ["srt", "video", "docx"])
    srt_mode: str = "bilingual"            # original|translation|bilingual
    burn_mode: str = "translation"         # original|translation|bilingual (压制视频用)
    cover_original: bool = True            # 是否遮盖原字幕
    out_dir: str = "."
    burn_font: str = "Arial"               # 压制字体
    burn_font_size: Optional[int] = None   # 压制字号(px)，None=按视频高度自动
    fonts_dir: Optional[str] = None
    sample_fps: float = 4.0


@dataclass
class JobResult:
    segments: List[Segment]
    files: dict = field(default_factory=dict)


def run_job(
    cfg: JobConfig,
    translator=None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> JobResult:
    def report(p, msg):
        if progress_cb:
            progress_cb(p, msg)

    base = os.path.splitext(os.path.basename(cfg.video_path))[0]
    os.makedirs(cfg.out_dir, exist_ok=True)
    workdir = os.path.join(cfg.out_dir, f".{base}_work")
    os.makedirs(workdir, exist_ok=True)

    # 1. Extract ------------------------------------------------------------
    report(0.02, "初始化识别引擎 / Init OCR")
    engine = build_engine(cfg.ocr_engine, OCRConfig())
    extractor = SubtitleExtractor(engine=engine,
                                  config=ExtractConfig(sample_fps=cfg.sample_fps))
    segments = extractor.extract(
        cfg.video_path,
        progress_cb=lambda p, m: report(0.02 + 0.58 * p, m),
    )
    if not segments:
        raise RuntimeError("未识别到任何字幕 / No captions detected.")

    # 2. Translate ----------------------------------------------------------
    if translator is None:
        from .translate import DeepLTranslator
        translator = DeepLTranslator(cfg.api_key)
    report(0.62, "翻译中 / Translating")
    texts = [s.text for s in segments]
    translations = translator.translate_lines(
        texts, cfg.target_lang, source_lang=cfg.source_lang,
        progress_cb=lambda p, m: report(0.62 + 0.18 * p, m),
    )
    for s, tr in zip(segments, translations):
        s.translation = tr

    # 3. Outputs ------------------------------------------------------------
    files = {}
    tl = cfg.target_lang.replace("-", "").lower()

    if "srt" in cfg.outputs:
        report(0.82, "生成SRT / Writing SRT")
        srt_path = os.path.join(cfg.out_dir, f"{base}.{tl}.srt")
        outputs.write_srt(segments, srt_path, mode=cfg.srt_mode)
        files["srt"] = srt_path

    if "docx" in cfg.outputs:
        report(0.86, "生成Word / Writing Word")
        docx_path = os.path.join(cfg.out_dir, f"{base}.{tl}.docx")
        outputs.write_docx(segments, docx_path, target_lang=cfg.target_lang,
                           source_lang=cfg.source_lang, video_name=os.path.basename(cfg.video_path))
        files["docx"] = docx_path

    if "video" in cfg.outputs:
        report(0.9, "压制视频 / Burning video")
        font = cfg.burn_font
        fonts_dir = cfg.fonts_dir
        if cfg.target_lang.upper() in CJK_TARGETS and font == "Arial":
            font = _default_cjk_font()
        vid_path = os.path.join(cfg.out_dir, f"{base}.{tl}.mp4")
        outputs.burn_video(cfg.video_path, segments, vid_path, workdir,
                           mode=cfg.burn_mode, font=font,
                           font_size=cfg.burn_font_size, fonts_dir=fonts_dir,
                           cover_original=cfg.cover_original)
        files["video"] = vid_path

    report(1.0, "完成 / Done")
    return JobResult(segments=segments, files=files)


def _default_cjk_font() -> str:
    """Best-effort CJK font family name available on common OSes."""
    import platform
    sys = platform.system()
    if sys == "Windows":
        return "Microsoft YaHei"
    if sys == "Darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"
