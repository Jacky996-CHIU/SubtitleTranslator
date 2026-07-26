"""
End-to-end orchestration: extract -> translate -> write outputs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .cache import Cache
from .extractor import SubtitleExtractor, Segment, ExtractConfig
from .ocr_engine import OCRConfig, build_engine
from .encoder import describe, detect_encoder
from .inpaint import remove_hardsubs
from .ocr_postprocess import OCRQuality, score_captions
from .qc import QCReport, check as qc_check
from .style import SubtitleStyle
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
    use_cache: bool = True                 # PRD 十三: 改样式不得重跑 OCR/DeepL
    cache_dir: Optional[str] = None
    removal_mode: str = "cover"            # cover | inpaint (PRD 八 AI 去字幕)
    style: Optional[SubtitleStyle] = None  # PRD 九 字幕样式
    encoder: Optional[str] = None          # None = auto-detect (GPU if usable)
    use_gpu: bool = True                   # PRD 十五 GPU 自动检测
    strict_qc: bool = False                # PRD 十一 检查通过后才允许导出


@dataclass
class JobResult:
    segments: List[Segment]
    files: dict = field(default_factory=dict)
    quality: Optional[OCRQuality] = None
    qc: Optional[QCReport] = None
    from_cache: bool = False


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

    cache = Cache(cfg.cache_dir, enabled=cfg.use_cache)

    # 1. Extract (cached) ---------------------------------------------------
    ocr_key = cache.ocr_key(cfg.video_path, cfg.ocr_engine, cfg.sample_fps)
    cached = cache.get_ocr(ocr_key)
    line_confs: List[float] = []
    cover_windows: List[tuple] = []
    from_cache = False
    if cached:
        report(0.55, "读取 OCR 缓存 / OCR cache hit")
        segments = [Segment(**{**d, "orig_box": tuple(d["orig_box"])
                              if d.get("orig_box") else None})
                    for d in cached["segments"]]
        cover_windows = [(a, b, tuple(box))
                         for a, b, box in cached.get("cover_windows", [])]
        from_cache = True
    else:
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
        line_confs = list(getattr(engine, "last_confidences", []))
        cover_windows = list(getattr(extractor, "cover_windows", []))
        cache.put_ocr(ocr_key, segments, cover_windows)

    # 2. Translate (cached per source line) ---------------------------------
    if translator is None:
        from .translate import DeepLTranslator
        translator = DeepLTranslator(cfg.api_key)
    report(0.62, "翻译中 / Translating")
    tkey = cache.translate_key(cfg.target_lang, cfg.source_lang)
    memo = cache.get_translations(tkey)
    texts = [s.text for s in segments]
    todo = [t for t in dict.fromkeys(texts) if t and t not in memo]
    if todo:
        fresh = translator.translate_lines(
            todo, cfg.target_lang, source_lang=cfg.source_lang,
            progress_cb=lambda p, m: report(0.62 + 0.18 * p, m),
        )
        memo.update({src: tr for src, tr in zip(todo, fresh)})
        cache.put_translations(tkey, memo)
    for s in segments:
        s.translation = memo.get(s.text, "")

    # 3. Pre-export quality check (PRD 十一) --------------------------------
    quality = score_captions([s.text for s in segments], line_confs)
    report(0.80, "质量检查 / Quality check")
    dims = outputs._probe_dims(cfg.video_path)
    qc_report = qc_check(segments, dims, target_lang=cfg.target_lang,
                         burn_mode=cfg.burn_mode,
                         min_conf_flagged=quality.low_conf_count)
    if cfg.strict_qc and not qc_report.ok:
        detail = "\n".join(str(f) for f in qc_report.errors[:12])
        raise RuntimeError("导出前质量检查未通过 / Quality check failed:\n" + detail)

    # 4. Outputs ------------------------------------------------------------
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
        font = cfg.burn_font
        fonts_dir = cfg.fonts_dir
        if cfg.target_lang.upper() in CJK_TARGETS and font == "Arial":
            font = _default_cjk_font()

        style = cfg.style
        if style is not None and not style.font:
            style.font = font

        vid_path = os.path.join(cfg.out_dir, f"{base}.{tl}.mp4")

        # AI 去字幕: 重绘模式先把原字幕笔画抹掉并重建背景，再叠加译文；
        # 覆盖模式直接用 drawbox 遮住原字幕。
        source_video = cfg.video_path
        audio_from = None
        cover = cfg.cover_original
        if cfg.removal_mode == "inpaint":
            report(0.9, "去除原字幕 / Removing original captions")
            clean = os.path.join(workdir, "clean.mp4")
            remove_hardsubs(cfg.video_path, clean, segments,
                            progress_cb=lambda p, m: report(0.9 + 0.05 * p, m))
            source_video = clean
            audio_from = cfg.video_path      # intermediate has no audio
            cover = False                    # already removed

        # GPU 自动检测 (PRD 十五): pick the fastest encoder that really works.
        enc = cfg.encoder
        if enc is None:
            enc = detect_encoder(outputs.ffmpeg_with_subtitles(),
                                 allow_gpu=cfg.use_gpu)
        report(0.95, f"压制视频 / Burning video · {describe(enc)}")
        outputs.burn_video(source_video, segments, vid_path, workdir,
                           mode=cfg.burn_mode, font=font,
                           font_size=cfg.burn_font_size, fonts_dir=fonts_dir,
                           cover_original=cover, style=style,
                           audio_from=audio_from, encoder=enc,
                           cover_windows=cover_windows)
        files["video"] = vid_path

    report(1.0, "完成 / Done")
    return JobResult(segments=segments, files=files, quality=quality,
                     qc=qc_report, from_cache=from_cache)


def _default_cjk_font() -> str:
    """Best-effort CJK font family name available on common OSes."""
    import platform
    sys = platform.system()
    if sys == "Windows":
        return "Microsoft YaHei"
    if sys == "Darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"
