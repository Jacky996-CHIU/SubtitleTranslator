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

## 模块（PRD 十八 模块化）

| 模块 | 文件 | 说明 |
|------|------|------|
| 视频导入 / UI | `gui/app.py` | PRD 流程：导入→语言→样式→处理→预览→导出 |
| 实时预览 | `gui/preview.py` | 播放/拖动 + 按当前样式重绘（不重跑 OCR/翻译） |
| 样式编辑 | `gui/style_panel.py`, `subtrans/style.py` | 字体/字号/颜色/描边/阴影/背景/位置 |
| OCR | `subtrans/ocr_engine.py`, `extractor.py` | 二次识别、逐词置信度、每帧重识别 |
| OCR 后处理 | `subtrans/ocr_postprocess.py` | 去重、上下文纠错、质量评分 |
| 翻译 | `subtrans/translate.py` | DeepL；相同文本不重复调用 |
| 去字幕 | `subtrans/cover.py`（黑底遮盖，默认）、`inpaint.py`（重绘，可选） | 黑底窗口来自 OCR 每帧验证过的行框 |
| 渲染/导出 | `subtrans/outputs.py` | ASS + ffmpeg；保持分辨率/帧率/音频 |
| 缓存 | `subtrans/cache.py` | OCR 与翻译缓存；改样式只重渲染 |
| 质量检查 | `subtrans/qc.py` | 导出前 OCR/翻译/字幕/去字幕四类检查 |
| GPU | `subtrans/encoder.py` | VideoToolbox/NVENC/QSV/AMF，试编码确认 |

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

## 易踩坑（已修，勿回退）

- **ffmpeg 必须带 libass**：Homebrew 的 ffmpeg 可能没编 libass，`subtitles` 滤镜
  根本不存在 → 压制永远失败。`outputs.ffmpeg_with_subtitles()` 会挑一个真正
  具备该滤镜的 ffmpeg（优先 `imageio-ffmpeg` 的静态版），否则报明确错误。
- **不要复用相邻帧的 OCR 结果**：`ExtractConfig.reuse_similar_frames=False`。
  开启会让淡入帧的残缺识别污染整条字幕，导致整行永久丢失。
- **黑底要用每帧的行框并集**，不是分段中位数框：多行字幕的行可能被分到不同
  时间段的 segment，用中位数框会漏挡（`extractor._build_cover_windows`）。
- **不要用亮度阈值扫描画面找字幕**来生成黑底：白色物体/仪表屏会被当成文字，
  黑底会膨胀到占屏近一半。

## 约束

- Tesseract 与 ffmpeg 是外部二进制，需安装或由打包脚本内置；不是 pip 包。
- macOS `.app`/`.dmg` 必须在 macOS 上构建，Windows `.exe` 必须在 Windows 上构建。
- 翻译走 DeepL，需用户自备 API 密钥；免费版每月 50 万字符。
