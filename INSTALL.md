# 安装与使用说明 · SubtitleTranslator

面向**最终用户**的安装指南。识别视频硬字幕 → DeepL 翻译 → 导出 SRT / 压制视频 / Word。

---

## 一、你需要准备什么

| 项目 | 是否必需 | 说明 |
|------|---------|------|
| SubtitleTranslator 软件 | ✅ 必需 | macOS 用 `.dmg`,Windows 用 `.zip` |
| **ffmpeg** | ⚠️ 见下 | 读取视频、压制字幕。若你拿到的是**自包含版**(CI 产出)则已内置,无需另装 |
| **tesseract** | ⚠️ 见下 | 文字识别(OCR)。自包含版已内置 |
| DeepL API 密钥 | ✅ 翻译时必需 | 免费版每月 50 万字符,密钥以 `:fx` 结尾 |

> **怎么判断要不要自己装 ffmpeg/tesseract?**
> 打开软件试跑一个视频。若提示找不到 `ffmpeg` 或 `tesseract`,就按下面对应系统的步骤装一次即可。**通过 GitHub Actions 打出的包已内置这两个工具**,通常无需安装。

---

## 二、macOS 安装

1. 双击 `SubtitleTranslator.dmg`,把 **SubtitleTranslator** 拖进「应用程序」。
2. **首次打开被拦截**(“无法验证开发者 / 已损坏”)——因为软件未做苹果签名,属正常现象。二选一解除:
   - **右键点图标 → 打开 → 再点“打开”**;或
   - 打开「终端」执行:
     ```bash
     xattr -dr com.apple.quarantine /Applications/SubtitleTranslator.app
     ```
3. (仅当提示缺工具时)安装 ffmpeg + tesseract。先装 Homebrew,再装工具:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install ffmpeg tesseract
   ```

## 三、Windows 安装

1. 解压 `SubtitleTranslator-windows.zip` 到任意文件夹(如 `C:\SubtitleTranslator`)。
2. 双击文件夹里的 **SubtitleTranslator.exe** 运行。
   - 若弹出 “Windows 已保护你的电脑”,点 **更多信息 → 仍要运行**(未签名程序的正常提示)。
3. (仅当提示缺工具时)安装 ffmpeg + tesseract。用管理员身份打开 PowerShell:
   ```powershell
   choco install tesseract ffmpeg -y
   ```
   > 没有 choco?去 https://ffmpeg.org 和 https://github.com/UB-Mannheim/tesseract/wiki
   > 下载安装,并把它们的 `bin` 目录加入系统 PATH。

---

## 四、获取 DeepL 密钥

1. 注册 https://www.deepl.com/pro-api ,选 **Free** 计划(每月 50 万字符,免费)。
2. 在账户页复制 **Authentication Key**,形如 `xxxxxxxx-xxxx-...:fx`(`:fx` 结尾表示免费版)。
3. 在软件里粘贴该密钥即可翻译。

---

## 五、基本使用

1. 打开软件 → **选择视频**。
2. 选**目标语言**(如中文 ZH),粘贴 **DeepL 密钥**。
3. 勾选要导出的内容:
   - **SRT 字幕**:原文 / 译文 / 双语可选
   - **压制视频**:把译文烧进画面,可**遮盖原字幕**
   - **Word 文档**:原文-译文对照表
4. 点**开始**,等待进度条完成。输出在你指定的目录。

> 只想识别原文、不翻译(不需要密钥):用「仅识别」模式,导出原文 SRT。

---

## 六、常见问题

| 现象 | 原因 / 处理 |
|------|------------|
| 提示找不到 ffmpeg / tesseract | 按第二、三节装一次;或改用**自包含版**的安装包 |
| 识别漏字、错字多 | 换 **PaddleOCR** 引擎(精度更高);确保字幕清晰、非花哨字体 |
| 中文/日文字幕压制后变方框 | 选带 CJK 字形的字体,如 `Noto Sans CJK SC` |
| 翻译报错 403 / 456 | 密钥错误或本月额度用尽(免费版 50 万字符/月) |
| 压制后原字幕仍隐约可见 | 开启**遮盖原字幕**;漏识别的行用 PaddleOCR 可减少 |

---

## 七、命令行(可选,进阶用户)

免安装图形界面也能用脚本批处理:

```bash
python3 cli.py 视频.mp4 --target ZH --api-key 你的:fx密钥 \
  --outputs srt video docx --out ./out \
  --font "Noto Sans CJK SC" --burn-mode bilingual --srt-mode translation
```

只识别不翻译(免密钥):

```bash
python3 cli.py 视频.mp4 --extract-only --out ./out
```
