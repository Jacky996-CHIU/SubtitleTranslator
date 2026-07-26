# 字幕翻译 · SubtitleTranslator

识别视频成片里**烧录进画面的字幕**（硬字幕），用 **DeepL** 翻译成任意目标语言，然后导出：

- **SRT 字幕文件**（可选：双语 / 仅译文 / 仅原文）
- **压制视频**：把译文字幕重新烧录进视频，并可遮盖原字幕，导出新的 MP4
- **Word 文档**：逐条对照的原文 / 译文表格

跨平台：**macOS 与 Windows 通用**。界面为中英双语。

> Recognizes hardcoded (burned-in) captions in finished videos, translates them
> with DeepL, and exports bilingual **SRT**, a re-burned **MP4**, and a **Word**
> document. Runs on macOS and Windows.

---

## 1. 识别精度 / Recognition

- **内置引擎 Tesseract**（默认，零额外安装）：对清晰的粗体硬字幕，配合本项目的
  白字掩膜 + 形态学分行 + 逐行置信度过滤 + 多帧投票，识别率高、抗背景干扰。
- **可选引擎 PaddleOCR**（推荐追求最高精度时安装）：`pip install paddleocr paddlepaddle`，
  对花体 / 复杂背景更强。程序在“自动”模式下检测到已安装即优先使用。

识别流程做了两件关键的事来保证精度：
1. **多帧投票**：每条字幕在画面上停留数秒、跨越很多帧，程序对同一条字幕的多帧
   识别结果做聚类投票，动画/淡入淡出的残帧会被“票数”淘汰。
2. **持续性过滤**：只保留在该字幕段大多数帧里稳定出现的文本行，闪现的背景文字
   （logo、仪表读数）会被剔除。

---

## 2. 安装 / Install

### 方式 A：下载打包好的软件（推荐给最终用户）
从 Releases 或你收到的压缩包里取：
- Windows：解压后运行 `SubtitleTranslator.exe`
- macOS：打开 `SubtitleTranslator.app`（首次打开若提示未验证开发者，右键→打开）

### 方式 B：从源码运行 / 自行打包（开发者）
```bash
# 1) 依赖
python3 -m pip install -r requirements.txt
#    可选高精度引擎：
#    pip install paddleocr paddlepaddle

# 2) 外部工具（必须在 PATH 中）
#    tesseract：  brew install tesseract   |  choco install tesseract
#    ffmpeg：     brew install ffmpeg      |  choco install ffmpeg

# 3) 运行界面
python3 gui/app.py
```

---

## 3. 使用 / Usage（GUI）

1. 拖入一个或多个视频（或点“添加视频”）。
2. 填入你的 **DeepL API 密钥**（免费版密钥以 `:fx` 结尾），点“验证密钥/刷新语言”
   载入 DeepL 支持的全部目标语言。
3. 选择目标语言、识别引擎、需要的输出（SRT / 压制视频 / Word）、输出目录。
4. 点“开始”。完成后自动打开输出目录。

密钥保存在本机配置文件里（`~/.config/SubtitleTranslator/` 或系统对应目录），不会上传。

### 命令行 / CLI
```bash
# 列出 DeepL 目标语言
python3 cli.py --api-key YOUR_KEY --list-langs

# 翻译成简体中文，导出三种结果
python3 cli.py video.mp4 --target ZH --api-key YOUR_KEY \
        --outputs srt video docx --out ./out

# 只识别原文字幕（不翻译，无需密钥），导出原文 SRT
python3 cli.py video.mp4 --extract-only --out ./out
```

---

## 4. 打包成软件 / Packaging

在**对应操作系统上**运行（PyInstaller 只能为当前系统构建）：

- Windows：双击 `build\build_win.bat` → 生成 `dist\SubtitleTranslator\SubtitleTranslator.exe`
- macOS：`bash build/build_mac.sh` → 生成 `dist/SubtitleTranslator.app`（脚本末尾附打 DMG 命令）

**一次性构建 Mac + Win 两个安装包**：把项目推到 GitHub，打一个 `v1.0.0` 标签，
`.github/workflows/build.yml` 会在 GitHub 的 macOS 和 Windows 机器上自动构建，
并在 Actions 里产出 `SubtitleTranslator-macos.dmg` 与 `SubtitleTranslator-windows.zip`。
这是从单台机器同时得到两个平台原生安装包最可靠的方式。

> 说明：真正的 macOS `.app/.dmg` 必须在 macOS 上构建（签名/公证同理），
> Windows `.exe` 必须在 Windows 上构建。源码 + 构建脚本 + 上面的 CI 覆盖了全部三条路径。

---

## 5. 项目结构 / Layout

```
SubtitleTranslator/
├── subtrans/
│   ├── ocr_engine.py     # Tesseract / PaddleOCR 引擎与字幕行检测
│   ├── extractor.py      # 采样 + 分段 + 多帧投票 + 时间轴
│   ├── translate.py      # DeepL 接入
│   ├── outputs.py        # SRT / ASS / ffmpeg 压制 / Word 导出
│   ├── pipeline.py       # 端到端编排
│   └── settings.py       # 本地设置
├── gui/app.py            # PySide6 跨平台界面
├── cli.py                # 命令行
├── build/                # PyInstaller spec + win/mac 构建脚本
├── .github/workflows/    # 自动构建 Mac + Win 的 CI
└── requirements.txt
```

## 6. 依赖的外部工具
- **Tesseract OCR**（识别）—— 打包脚本会尝试把它一并打进应用；否则用系统安装的版本。
- **ffmpeg / ffprobe**（压制视频）—— 同上。

翻译使用 **DeepL API**：免费版每月 50 万字符，注册即得密钥。
