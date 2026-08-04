# PDF 阅读翻译器 / PDF Reader & Translator

一个类似「知云文献翻译」的桌面 PDF 阅读翻译工具，使用 Python + PyQt6 开发。

A desktop PDF reader & translator similar to "Zhiyun Literature Translation", built with Python + PyQt6.

左侧查看 PDF，右侧显示翻译结果；用鼠标刷选 PDF 内容即可翻译，支持记录阅读位置，下次从上次位置继续阅读。

View the PDF on the left and the translation on the right. Select text in the PDF with your mouse to translate it. Your reading position is remembered so you can resume where you left off.

---

## 功能特性 / Features

- 📄 **PDF 阅读**：按需渲染，打开大文件也不卡顿；支持适合页面 / 适合宽度 / 百分比三种缩放模式
- 🖱️ **鼠标刷选翻译**：按段落刷选文本，保持句子连续性，翻译效果更好
- 🎯 **浮动翻译按钮**：刷选文本后，翻译按钮自动出现在鼠标附近，点击即可翻译，无需移动鼠标
- 🌐 **多翻译引擎**：内置微软 Edge、通用 OpenAI 兼容大模型、MyMemory 三个接口，可自动回退或手动选择
- 🤖 **AI 总结**：针对当前页调用大模型生成结构化总结，流式输出实时显示，独立可缩放窗口，支持 Markdown 渲染
- ⚙️ **大模型设置**：支持任意 OpenAI 兼容服务商（OpenAI、DeepSeek、智谱、硅基流动、本地 Ollama 等），模型名可从服务商下拉拉取
- 📌 **阅读位置记忆**：自动记录每个 PDF 的阅读位置，下次打开自动跳转
- 🕘 **最近打开历史**：记录最近打开的 10 个文件，支持一键清空
- 🔗 **PDF 链接可点击**：悬停显示手型光标，点击用系统浏览器打开
- ⌨️ **快捷键**：`Ctrl + / Ctrl -` 调节缩放，`Ctrl + L` 切换全屏，`Ctrl + T` 翻译
- 🔐 **API Key 安全存储**：大模型 Key 存入 Windows 凭据管理器（keyring），不落盘明文
- 🕐 **状态栏日期时间**：右下角实时显示当前日期和时间
- 🎨 **界面美化**：自定义 QSS 样式、可调翻译字体、内置 Logo、关于对话框

---

- 📄 **PDF reading**: on-demand rendering, smooth even for large files; supports Fit Page / Fit Width / Percentage zoom modes
- 🖱️ **Select-to-translate**: selects text by paragraph to preserve sentence continuity for better translations
- 🎯 **Floating translate button**: appears near the mouse after selecting text; click to translate without moving the mouse
- 🌐 **Multiple translation engines**: built-in Microsoft Edge, generic OpenAI-compatible LLM, and MyMemory, with auto-fallback or manual selection
- 🤖 **AI summary**: summarizes the current page via LLM with streaming output, shown in a resizable standalone window with Markdown rendering
- ⚙️ **LLM settings**: supports any OpenAI-compatible provider (OpenAI, DeepSeek, Zhipu, SiliconFlow, local Ollama, etc.); model names can be fetched from the provider
- 📌 **Reading position memory**: automatically remembers the position of each PDF and resumes there next time
- 🕘 **Recent files**: remembers the last 10 opened files, with one-click clear
- 🔗 **Clickable PDF links**: shows a hand cursor on hover, opens in the system browser on click
- ⌨️ **Shortcuts**: `Ctrl + / Ctrl -` to zoom, `Ctrl + L` to toggle fullscreen, `Ctrl + T` to translate
- 🔐 **Secure API key storage**: LLM key is stored in the Windows Credential Manager (keyring), never in plaintext
- 🕐 **Status bar clock**: shows the current date and time in the bottom-right corner
- 🎨 **Polished UI**: custom QSS styling, adjustable translation font, built-in logo, About dialog

---

## 安装 / Installation

需要 Python 3.9+。

Requires Python 3.9+.

```bash
# 克隆仓库 / Clone the repository
git clone https://github.com/your-username/pdf-translator.git
cd pdf_translator

# 安装依赖 / Install dependencies
pip install -r requirements.txt

# 国内用户可使用清华源加速 / Chinese users can use the Tsinghua mirror
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行 / Run

```bash
python main.py
```

---

## 使用说明 / Usage

1. 点击「打开 PDF」或使用 `Ctrl + O` 打开一个 PDF 文件
2. 在左侧 PDF 中用鼠标刷选要翻译的文本，翻译按钮会出现在鼠标附近，点击即可翻译
3. 翻译结果显示在右侧；也可点击「翻译选中内容」或按 `Ctrl + T`
4. 可在右上角选择翻译引擎（自动 / 微软 Edge / 大模型 / MyMemory）
5. 使用「A- / A+」按钮调节翻译字体大小
6. 点击工具栏「AI 总结」对当前页生成总结，结果在独立窗口中流式显示
7. 首次使用大模型翻译或总结前，请到「设置 → 大模型设置」填写接口地址、API Key 和模型名
8. 关闭程序后，下次打开同一 PDF 会自动跳转到上次阅读位置

---

1. Click "Open PDF" or press `Ctrl + O` to open a PDF file
2. Select the text you want to translate in the PDF on the left; a translate button appears near the mouse — click it to translate
3. The result appears on the right; you can also click "Translate Selected" or press `Ctrl + T`
4. Choose a translation engine in the top-right (Auto / Microsoft Edge / LLM / MyMemory)
5. Use the "A- / A+" buttons to adjust the translation font size
6. Click "AI Summary" in the toolbar to summarize the current page; the result streams into a standalone window
7. Before using LLM translation or summary for the first time, configure the base URL, API key, and model under "Settings → LLM Settings"
8. After closing, reopening the same PDF resumes at your last reading position

---

## 大模型设置 / LLM Settings

本软件支持任意 **OpenAI 兼容** 的大模型接口，由用户自行选择服务商并填写：

This software supports any **OpenAI-compatible** LLM endpoint. You choose the provider and fill in:

- **接口地址 (Base URL)**：例如 `https://api.openai.com/v1`、`https://api.deepseek.com/v1`、`https://api.siliconflow.cn/v1` 等
- **API Key**：从服务商获取，安全存入 Windows 凭据管理器
- **模型名 (Model)**：可手动输入，或点击「刷新模型」从服务商自动拉取下拉列表

- **Base URL**: e.g. `https://api.openai.com/v1`, `https://api.deepseek.com/v1`, `https://api.siliconflow.cn/v1`, etc.
- **API Key**: obtained from the provider, securely stored in the Windows Credential Manager
- **Model**: can be typed manually, or fetched from the provider via the "Refresh Models" button

---

## 项目结构 / Project Structure

```
pdf_translator/
├── main.py          # 主窗口：分栏布局、工具栏、菜单栏、翻译/总结线程、浮动按钮
├── pdf_viewer.py    # PDF 阅读器：按需渲染、刷选、缩放、链接点击
├── translator.py    # 翻译引擎：Edge / OpenAI 兼容大模型 / MyMemory，流式总结
├── settings.py      # 配置存储：阅读位置、最近历史、界面设置、大模型配置
├── make_logo.py     # Logo 生成脚本
├── requirements.txt # 依赖清单
└── logo.ico / logo.png  # 应用图标
```

---

## 技术栈 / Tech Stack

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — 桌面 GUI 框架
- [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) — PDF 渲染与文本提取
- [requests](https://requests.readthedocs.io/) — 调用翻译 / 大模型 API
- [keyring](https://github.com/jaraco/keyring) — 系统凭据管理器（安全存储 API Key）

---

## 翻译引擎 / Translation Engines

| 引擎 / Engine | 说明 / Description | 需要 Key |
| --- | --- | --- |
| 微软 Edge / Microsoft Edge | 官方翻译接口，质量稳定 | 否 |
| 大模型 / LLM | 通用 OpenAI 兼容大模型，翻译质量高，可做 AI 总结 | 是（可选） |
| MyMemory | 免费在线翻译服务 | 否 |

选择「自动」时，程序会依次尝试各引擎，直到成功为止。

When "Auto" is selected, the program tries each engine in turn until one succeeds.

---

## 许可证 / License

[MIT](LICENSE)

---

## 致谢 / Acknowledgements

- 灵感来自「知云文献翻译」/ Inspired by "Zhiyun Literature Translation"
- 感谢 PyQt6、PyMuPDF 等开源项目 / Thanks to PyQt6, PyMuPDF and other open-source projects
