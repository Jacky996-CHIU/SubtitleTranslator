# CLAUDE.md — 项目说明（给 Claude Code）

视频硬字幕识别 → DeepL 翻译 → 导出 **SRT / 压制视频 / Word** 的跨平台桌面软件
（macOS + Windows）。本文件给 Claude Code 提供上下文与"在哪调参数"的索引。

## 运行 / 验证

```bash
python3 -m pip install -r requirements.txt      # 依赖
# 外部工具需在 PATH: tesseract、ffmpeg (brew install tesseract ffmpeg)
# 可选高精度引擎: pip install paddleocr paddlepaddle

python3 gui/app.py                               # 图形界面
python3 cli.py VIDEO --target ZH --api-key KEY --outputs srt video docx --out ./out
python3 cli.py VIDEO --extract-only --out ./out  # 只识别原文,不翻译(免密钥)
python3 tests/test_deepl_integration.py          # DeepL 接入离线测试(6项)
```

## 架构（数据流）

`gui/app.py` 或 `cli.py`
  → `subtrans/pipeline.py: run_job(JobConfig)` 编排：
    1. **识别** `subtrans/extractor.py: SubtitleExtractor.extract()`
       - 采样帧 → `subtrans/ocr_engine.py` 检测字幕行 → 分段 → 多帧投票 → 时间轴
       - 引擎: `TesseractOCR`(默认/内置) 或 `PaddleOCR`(可选/高精度)
    2. **翻译** `subtrans/translate.py: DeepLTranslator.translate_lines()`
       - 后端二选一: `_SDKBackend`(deepl SDK) 或 `_RESTBackend`(requests 直连)
       - 免费密钥(`:fx`)走 api-free.deepl.com，付费走 api.deepl.com
    3. **输出** `subtrans/outputs.py`: `write_srt` / `burn_video` / `write_docx`
- 设置持久化: `subtrans/settings.py`（`_DEFAULTS` 是所有默认值的单一来源）

## 四个常调开关 —— 在哪改

| 需求 | 默认值来源 | CLI 参数 | 代码位置 |
|------|-----------|---------|---------|
| **字体** | `settings.py _DEFAULTS["burn_font"]`（""=自动） | `--font "Noto Sans CJK SC"` | `outputs.py: write_ass(font=...)`；中日韩自动字体见 `pipeline.py: _default_cjk_font()` |
| **字号** | `settings.py _DEFAULTS["burn_font_size"]`（0=自动） | `--font-size 24` | `outputs.py: burn_video(font_size=...)`；自动值公式 `fs = max(18, int(h*0.062))` |
| **遮盖原字幕** | `settings.py _DEFAULTS["cover_original"]`（True） | `--cover / --no-cover` | `outputs.py: burn_video(cover_original=...)` → `_cover_filters()` 用 OCR 检出的 `Segment.orig_box` 画黑框遮盖 |
| **双语/纯译文** | SRT: `srt_mode`；压制视频: `burn_mode` | `--srt-mode` / `--burn-mode`（original\|translation\|bilingual） | `outputs.py: write_srt(mode=)` 和 `write_ass(mode=)` |

改默认值 → 编辑 `subtrans/settings.py` 的 `_DEFAULTS`（GUI 会读它；同时 `JobConfig`
里有对应字段，CLI/调用方可覆盖）。

## 其它可调点（识别精度相关）

- 字幕区域/字号阈值/置信度/全大写偏好: `subtrans/ocr_engine.py: OCRConfig`
  （`region_top`、`min_line_height`、`min_conf=62`、`uppercase_bias` 等）
- 采样率/分段合并/最短时长: `subtrans/extractor.py: ExtractConfig`
  （`sample_fps`、`merge_similarity`、`min_duration`、`_vote(support=0.4)` 持续性阈值）
- 压制字幕位置/描边/盒底色: `outputs.py: write_ass()` 的 style 行

## 压制视频遮盖逻辑（易踩）

`burn_video(cover_original=True)` 只遮盖**被 OCR 检测到**的原字幕行
（`Segment.orig_box` 来自 `ocr_engine` 的 `last_boxes`）。若某行漏识别，则那行不会被
遮住——用 PaddleOCR 引擎可显著减少漏识别。

## 打包

- 本机构建: `build/build_win.bat`(Win) / `bash build/build_mac.sh`(mac)
- 自动双平台: 推 tag → `.github/workflows/build.yml` 产出 `.dmg` + `.exe`
- PyInstaller 配置: `build/SubtitleTranslator.spec`（会尝试把 ffmpeg/tesseract 一并打包）

## 约束

- Tesseract 与 ffmpeg 是外部二进制，需安装或由打包脚本内置；不是 pip 包。
- macOS `.app`/`.dmg` 必须在 macOS 上构建，Windows `.exe` 必须在 Windows 上构建。
- 翻译走 DeepL，需用户自备 API 密钥；免费版每月 50 万字符。
