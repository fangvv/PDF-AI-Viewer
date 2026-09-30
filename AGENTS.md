# AGENTS.md — 给 AI 助手的项目说明

本文件面向**后续进入此仓库的 AI 助手 / 开发者**，提供工程上下文与约定，避免重复摸索。
面向用户的介绍请看 [README.md](README.md)。

## 项目是什么

一个类似「知云文献翻译」的桌面 PDF 阅读翻译工具，Python + PyQt6 开发。
左侧阅读 PDF（可刷选文本），右侧显示翻译结果；支持多翻译引擎、AI 总结、
边读边问的多轮 AI 问答（问答追加到同名 .md 笔记）、阅读位置记忆。

## 技术栈与依赖

- Python 3.9+（当前开发环境为 3.13）
- PyQt6 — GUI
- PyMuPDF (`pymupdf`) — PDF 渲染与文本提取
- requests — 调用翻译 / 大模型 API
- keyring — 系统凭据管理器（安全存储 API Key）

依赖清单见 `requirements.txt`。

## 项目结构

```
main.py          # 主窗口：分栏布局、工具栏、菜单栏、翻译/总结/问答线程、浮动按钮、全局样式
pdf_viewer.py    # PDF 阅读器：按需渲染、刷选、缩放、链接点击
translator.py    # 翻译引擎：Edge / OpenAI 兼容大模型 / MyMemory，流式总结与多轮对话
chat_window.py   # AI 阅读问答：浮动对话窗口（气泡 HTML 渲染、流式显示、字号/主题）
chat_log.py      # 问答记录读写：与 PDF 同目录同名的 .md 笔记
latex_fallback.py # LaTeX 公式 → Unicode 兜底转换（总结与问答共用）
settings.py      # 配置存储：阅读位置、最近历史、界面设置、大模型配置、问答笔记回退目录
make_logo.py     # Logo 生成脚本（logo.ico / logo.png）
```

## 运行

```bash
python main.py
```

## 打包（重要）

用 PyInstaller，**必须通过 spec 文件**打包，不要直接 `pyinstaller main.py`：

```bash
pyinstaller --noconfirm "PDF阅读翻译器.spec"
```

产物在 `dist/PDF阅读翻译器.exe`。

### 打包陷阱（务必遵守）

1. **必须保留 spec 里的 `excludes` 列表**。PyMuPDF 的 `pymupdf.table` 模块会 `import pandas`，
   进而拖入 numpy / matplotlib / lxml / openpyxl / fontTools 等一整套数据科学库，
   导致 exe 从 ~65MB 膨胀到 ~110MB，超过 GitHub 100MB 文件限制导致无法推送。
   本项目只用 `pymupdf` 渲染 PDF，不需要这些库，已在 spec 中排除。
2. exe 约 65MB，超过 GitHub 50MB 推荐上限但低于 100MB 硬限制，可正常推送（会有警告）。
3. 若改动后 exe 体积异常增大，先检查是否又引入了被排除的依赖。
4. **打包后窗口/任务栏图标**：窗口/任务栏图标由 exe 运行时加载 `logo.ico`，必须在 spec 的
   `Analysis.datas` 里把 `logo.ico`/`logo.png` 打包进去（`datas=[('logo.ico', '.'), ('logo.png', '.')]`），
   并且代码里用 `resource_path()`（基于 `sys._MEIPASS`）解析，直接拼 `__file__` 目录在冻结环境找不到。
   spec 里 EXE 的 `icon=['logo.ico']` 只影响 exe 文件本身的图标，不影响运行时任务栏图标。
   另外 **PyQt6 没有 `QApplication.setAppUserModelID`**（会 AttributeError），设置 Windows 任务栏
   AppUserModelID 需用 `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`（见 `main()`）。

### 标准工作流（每次改代码后都要做）

每次修改代码后，**必须重新打包并上传到 GitHub**，否则仓库里的 exe 与源码不一致。
完整发布流程如下（按顺序执行）：

1. **清理不需要的文件**：删除本次改动产生的临时/无用文件（如调试脚本、临时图片、备份文件等），
   保持仓库整洁。注意 `dist/PDF阅读翻译器.exe` 和 `*.spec` 是**被 git 跟踪**的，不要误删。
2. **更新文档**：若功能有增删改，同步更新 `README.md`（面向用户的功能/使用说明）和
   `AGENTS.md`（面向 AI 助手/开发者的工程约定与坑）。README 保持中英双语。
3. **重新打包**：`pyinstaller --noconfirm "PDF阅读翻译器.spec"`
4. **确认体积**：检查 `dist/PDF阅读翻译器.exe` **小于 100MB**（GitHub 硬限制，超过会拒绝推送）
5. **提交并推送**：`git add` 源码 + spec + exe + 两个 md，然后 `git commit` + `git push`

> 若打包后 exe 超过 100MB，说明又引入了被排除的依赖，先排查再推送。

## 已知代码约定 / 坑

- **QTextEdit 字体调整**：必须用 `result_view.document().setDefaultFont(font)`，
  而不是 `result_view.setFont(font)`。后者不会改变已显示或后续 `setPlainText()`/`setHtml()`
  写入文本的字体（见 `main.py` 的 `_set_font_size`）。
- 翻译结果区提示文字 `_set_result_hint()` 用 HTML，字号需跟随 `self.font_size`，不要写死。
- 全局样式表 `_APP_STYLE` 定义在 `main.py` 底部。
- **PDF 库导入**：用 `import pymupdf`，不要用旧的 `import fitz`（兼容别名已弃用，每次启动会打印
  `warning: The `fitz` API is deprecated...`）。见 `pdf_viewer.py`。
- 大模型 API Key 通过 keyring 存 Windows 凭据管理器，不落盘明文。
- **窗口状态保存**：`saveGeometry()` 返回 `QByteArray`，**没有 `.hex()` 方法**（那是 Python
  `bytes` 的方法）。必须用 `bytes(self.saveGeometry()).hex()` 保存、用
  `restoreGeometry(QByteArray(bytes.fromhex(hex)))` 恢复（见 `main.py` 的
  `_save_window_state` / `_restore_settings`）。窗口状态在 `resizeEvent`/`moveEvent` 里用
  QTimer 防抖实时保存，`closeEvent` 里也保存。
- **全文总结**：`_summarize_current` 用 `viewer.document_text(max_chars=60000)` 取整篇文档
  文本（按页拼接、带页标记、截断防超上下文），不是单页。
- **LaTeX 公式显示**：`QTextEdit.setMarkdown` 不支持 LaTeX。总结 prompt 已要求模型用
  Unicode 数学符号；显示端 `SummaryWindow._latex_to_unicode` 做兜底转换（去 `$...$` 定界符、
  `\frac`→`(a)/(b)`、常用命令→Unicode、上下标）。注意 replacements 的 key 用**单反斜杠**
  raw string（`r"\alpha"`），不要写成 `r"\\alpha"`（那是两个反斜杠，匹配不到）。
- **全文搜索**：`PdfViewer.search()` 用 `page.search_for()` 返回 `(page_index, rect)` 列表；
  `scroll_to_rect()` 按 `w.y() + rect.y0*zoom - viewport_height/2` 让高亮垂直居中。
  搜索词未变时再点「搜索」跳到下一个结果（见 `_do_search` 的 `_last_search_text` 逻辑）。
- **主题（日间/夜间）**：`main.py` 底部定义 `_APP_STYLE`（日间）和 `_APP_STYLE_DARK`（夜间）
  两套全局样式表，`_set_theme()` 切换并保存到 settings.json 的 `theme` 字段（兼容旧 `dark_mode`）。
  切换时 `_apply_theme_to_widgets()` 同步更新硬编码颜色的控件（浮动按钮、A-/A+ 字体按钮、
  翻译提示文字、PDF 空状态提示）。**PDF 页面反色**：夜间模式下 `PdfPageWidget._render()` 对
  QImage 调 `img.invertPixels()`（白底→黑底）。注意：护眼模式（豆沙绿）已移除，不要重新引入。
- **内部链接跳转（参考文献）**：`PdfPageWidget` 解析 `page.get_links()` 中 `kind == 1` 的
  内部链接（目标页 + 目标矩形），点击时发 `internalLinkClicked` 信号；`PdfViewer.go_to_internal_link()`
  复用 `scroll_to_rect()` 跳转。外部 `uri` 链接仍走 `linkClicked` 用系统浏览器打开。
- **连续打开多个 PDF**：`PdfViewer._clear_pages()` 删除旧页面时，必须先 `layout.removeWidget(w)`
  再 `deleteLater()`。因为 `deleteLater()` 是延迟删除，若只 deleteLater 不 removeWidget，
  连续快速打开多个 PDF 时新旧页面会混在一起。
- **工具栏按钮状态**：未打开 PDF 时，"关闭 PDF"、"全文总结"、"AI 问答"、页码导航控件应禁用（灰色）。
  通过 `self.close_action` / `self.summary_action` / `self.chat_action` / `self.page_label` 等实例属性控制，
  在 `load_pdf` 启用、`close_pdf` 禁用。页码跳转框 `page_spin` 未打开时值应为 0（不是 1），
  避免显示误导性的"第 1 页"。工具栏内 QPushButton（搜索/上一个/下一个）用 `QToolBar QPushButton`
  选择器统一成与 QToolButton 一致的浅色描边风格，并定义 `:disabled` 状态让禁用可见。

- **AI 阅读问答（chat_window.py / chat_log.py）**：
  - **分工与 SummaryWindow 一致**：`ChatWindow` 只是视图，网络请求在 `main.py` 的 `ChatWorker(QThread)`，
    走 `translator.llm.chat_stream(history, doc_text)`（多轮 messages）。
  - **问答的系统提示词固定为 `"You are a helpful assistant."`、温度固定 0**，与 Chatbox 默认保持一致，
    **不要**再加自定义人设/「回答简洁」/禁 LaTeX 之类的指令（会把回答压短）。公式靠显示端
    `latex_fallback` 兕底，输出语言跟随用户提问。温度参数已提到
    `_stream_messages(temperature=0.3)`，总结等仍用默认 0.3，问答显式传 0。
  - **文献上下文像 Chatbox 附加文件一样注入**：`_on_chat_ask` 在 **GUI 线程**用
    `viewer.document_text(max_chars=CHAT_DOC_CHARS=60000)` 取全文（pymupdf 与渲染共用文档，
    跨线程取文本不安全），经 `ChatWorker(doc_text=...)` 传给 `chat_stream`，插在历史之前作为
    首对 user/assistant 消息（user：「以下是我正在阅读的文献内容：…」，assistant 简短确认）；
    **不要**把文献塞进系统提示词，也不注入文档名。扫描件/无文本 PDF 的 doc_text 为空，
    自动退回纯对话。笔记 `.md` 只存真实问答，不含文献文本。
  - **快捷键不能用 `Ctrl+Q`**：菜单「退出」用的是 `QKeySequence.StandardKey.Quit`，在 Windows 上就是
    `Ctrl+Q`。问答用 `Ctrl+Shift+Q`。
  - **笔记格式是可解析的**：每条问答以 `^## <序号>. 问：<问题>` 标题行开头，接 `> 第 N 页 · 时间`，
    再接 `**答：**` 与正文，最后 `---` 分隔。`chat_log._Q_RE` 就靠这个形状切分。改动格式必须同步改
    `load_chat_log` 的正则，否则旧笔记会解析不出来。
  - **写问题时把换行压成空格**（`" ".join(question.split())`），保证标题行始终单行、可回解析；
    代价是重新加载后多行问题变单行，可接受。
  - **解析失败要降级不能报错**：用户可能手改 `.md`。`load_chat_log` 找不到问题标题行时返回
    `([], 原文)`，界面按原文 Markdown 渲染并显示橙色提示条。
  - **写入失败要回退**：PDF 可能在只读目录/被占用。`append_exchange` 失败时退回
    `settings.chatnotes_dir()`（`~/.pdftranslator/chatnotes/`）并返回错误信息，绝不能静默丢内容。
  - **QTextBrowser 富文本不支持 `border-radius`**，所以气泡用嵌套 `<table bgcolor=...>` + `cellpadding`
    实现（内层 table 用 `align="right"` 才能收缩宽度，做成真正的气泡而不是整行色条）。
  - **Markdown 回答的颜色注入**：`QTextDocument.setMarkdown` + `toHtml()` 把字号写在 `<body>` 上、
    块级元素不带 `color`。提取 body 后用 `body.replace('style="', f'style="color:{color}; ')`
    统一注入，否则夜间模式文字是黑的。字号则通过 temp doc 的 `setDefaultFont` 控制（标题用相对字号，会跟随缩放）。
  - **流式输出必须限频重绘**：`_render_timer` 120ms 单发，每 tick 重绘一次整页；同时每条回答的
    Markdown 渲染结果缓存在条目上（`item["_html"] / item["_html_key"]`，key = (theme, font_px)），
    否则长历史会每帧重新解析，明显卡顿。
  - **改 `objectName` 切样式必须 unpolish/polish**：发送/停止按钮靠切换 objectName（`sendBtn`/`stopBtn`）
    换颜色，不重 polish 不会生效。
  - **被中断的回答仍写 `.md`**，但末尾追加 `（回答中断）`；完全失败（无内容）不写，避免脏数据。
  - **防串会话**：关闭/切换 PDF 会 `reset_session()`，此时迟到的 `finished` 信号靠
    `finish_answer`/`show_answer_error` 开头的「会话已重置」守卫丢弃；连续提问时 `_on_chat_ask`
    先 `stop()+wait()` 旧线程并 **disconnect 信号**，否则旧线程排队的 `finished` 泄入下一轮。
  - 问答窗口几何存在 `settings.json` 的 `chat_geometry`（hex，同 `window_geometry` 那套写法）。

- **`latex_fallback.py`**：原 `SummaryWindow._latex_to_unicode` 抽出来的共用模块，
  `SummaryWindow._latex_to_unicode` 现在只是薄封装。改公式转换只改这一处。

## 提交约定

- 提交信息用中文，遵循 `fix:` / `feat:` / `build:` 前缀（参考 git log）。
- `dist/PDF阅读翻译器.exe` 和 `*.spec` 是**被 git 跟踪**的（.gitignore 未忽略），
  重新打包后需一并提交。
- 注意：exe 超过 100MB 时 GitHub 会拒绝推送；若历史中混入超大 exe，
  需用 `git reset --soft` 合并/重写未推送提交来移除。
