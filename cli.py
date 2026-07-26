#!/usr/bin/env python3
"""
Command-line interface for SubtitleTranslator.

Examples
--------
List DeepL target languages::

    python cli.py --api-key YOUR_KEY --list-langs

Translate one video to Simplified Chinese, all three outputs::

    python cli.py video.mp4 --target ZH --api-key YOUR_KEY \
        --outputs srt video docx --out ./out

Extract original captions only (no translation, no key needed)::

    python cli.py video.mp4 --extract-only --out ./out
"""

from __future__ import annotations

import argparse
import os
import sys

from subtrans.pipeline import JobConfig, run_job
from subtrans.extractor import SubtitleExtractor, ExtractConfig
from subtrans.ocr_engine import OCRConfig, build_engine
from subtrans import outputs


def _progress(p, msg):
    bar = int(p * 30)
    sys.stdout.write(f"\r[{'#'*bar}{'.'*(30-bar)}] {p*100:5.1f}%  {msg:<32}")
    sys.stdout.flush()
    if p >= 1.0:
        sys.stdout.write("\n")


def main():
    ap = argparse.ArgumentParser(description="Video hardcoded-subtitle translator (DeepL)")
    ap.add_argument("video", nargs="?", help="input video file")
    ap.add_argument("--target", help="DeepL target language code, e.g. ZH, JA, DE")
    ap.add_argument("--source", default="EN", help="source language (default EN)")
    ap.add_argument("--api-key", default=os.environ.get("DEEPL_API_KEY", ""))
    ap.add_argument("--engine", default="tesseract", choices=["tesseract", "paddleocr"])
    ap.add_argument("--outputs", nargs="+", default=["srt", "video", "docx"],
                    choices=["srt", "video", "docx"])
    ap.add_argument("--srt-mode", default="bilingual",
                    choices=["original", "translation", "bilingual"],
                    help="SRT 内容：原文/译文/双语")
    ap.add_argument("--burn-mode", default="translation",
                    choices=["original", "translation", "bilingual"],
                    help="压制进视频的字幕：原文/译文/双语")
    ap.add_argument("--out", default="./out", help="output directory")
    ap.add_argument("--sample-fps", type=float, default=4.0)
    ap.add_argument("--font", default="Arial", help="压制字体名，如 'Noto Sans CJK SC'")
    ap.add_argument("--font-size", type=int, default=None,
                    help="压制字号(px)，默认按视频高度自动")
    cover = ap.add_mutually_exclusive_group()
    cover.add_argument("--cover", dest="cover", action="store_true",
                       help="遮盖原字幕(默认)")
    cover.add_argument("--no-cover", dest="cover", action="store_false",
                       help="不遮盖原字幕，译文叠加显示")
    ap.set_defaults(cover=True)
    ap.add_argument("--extract-only", action="store_true",
                    help="only OCR captions, write original SRT, no DeepL")
    ap.add_argument("--list-langs", action="store_true",
                    help="print DeepL target languages and exit")
    args = ap.parse_args()

    if args.list_langs:
        from subtrans.translate import DeepLTranslator
        t = DeepLTranslator(args.api_key)
        for l in t.target_languages():
            print(f"{l.code:8s} {l.name}")
        return

    if not args.video:
        ap.error("video is required")

    if args.extract_only:
        os.makedirs(args.out, exist_ok=True)
        ext = SubtitleExtractor(engine=build_engine(args.engine, OCRConfig()),
                                config=ExtractConfig(sample_fps=args.sample_fps))
        segs = ext.extract(args.video, progress_cb=_progress)
        base = os.path.splitext(os.path.basename(args.video))[0]
        path = os.path.join(args.out, f"{base}.original.srt")
        outputs.write_srt(segs, path, mode="original")
        print(f"\n{len(segs)} captions -> {path}")
        for s in segs:
            print(f"  [{s.index:02d}] {s.start:6.1f}-{s.end:6.1f}  {s.text.replace(chr(10),' / ')}")
        return

    if not args.target:
        ap.error("--target is required (or use --extract-only)")

    cfg = JobConfig(
        video_path=args.video, target_lang=args.target, source_lang=args.source,
        api_key=args.api_key, ocr_engine=args.engine, outputs=args.outputs,
        srt_mode=args.srt_mode, burn_mode=args.burn_mode,
        cover_original=args.cover, out_dir=args.out, sample_fps=args.sample_fps,
        burn_font=args.font, burn_font_size=args.font_size,
    )
    result = run_job(cfg, progress_cb=_progress)
    print("\nDone. Files:")
    for k, v in result.files.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
