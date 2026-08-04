# AGENTS.md — 给 AI 助手的项目说明

本文件面向**后续进入此仓库的 AI 助手 / 开发者**，提供工程上下文与约定，避免重复摸索。
面向用户的介绍请看 [README.md](README.md)。

## 项目是什么

一个类似「知云文献翻译」的桌面 PDF 阅读翻译工具，Python + PyQt6 开发。
左侧阅读 PDF（可刷选文本），右侧显示翻译结果；支持多翻译引擎、AI 总结、阅读位置记忆。

## 技术栈与依赖

- Python 3.9+（当前开发环境为 3.13）
- PyQt6 — GUI
- PyMuPDF (`fitz`) — PDF 渲染与文本提取
- requests — 调用翻译 / 大模型 API
- keyring — 系统凭据管理器（安全存储 API Key）

依赖清单见 `requirements.txt`。

## 项目结构

```
main.py          # 主窗口：分栏布局、工具栏、菜单栏、翻译/总结线程、浮动按钮、全局样式
pdf_viewer.py    # PDF 阅读器：按需渲染、刷选、缩放、链接点击
translator.py    # 翻译引擎：Edge / OpenAI 兼容大模型 / MyMemory，流式总结
settings.py      # 配置存储：阅读位置、最近历史、界面设置、大模型配置
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
   本项目只用 `fitz` 渲染 PDF，不需要这些库，已在 spec 中排除。
2. exe 约 65MB，超过 GitHub 50MB 推荐上限但低于 100MB 硬限制，可正常推送（会有警告）。
3. 若改动后 exe 体积异常增大，先检查是否又引入了被排除的依赖。

### 标准工作流（每次改代码后都要做）

每次修改代码后，**必须重新打包并上传到 GitHub**，否则仓库里的 exe 与源码不一致：

1. 修改代码
2. 重新打包：`pyinstaller --noconfirm "PDF阅读翻译器.spec"`
3. 确认 `dist/PDF阅读翻译器.exe` **小于 100MB**（GitHub 硬限制，超过会拒绝推送）
4. 提交并推送：`git add` 源码 + spec + exe，然后 `git commit` + `git push`

> 若打包后 exe 超过 100MB，说明又引入了被排除的依赖，先排查再推送。

## 已知代码约定 / 坑

- **QTextEdit 字体调整**：必须用 `result_view.document().setDefaultFont(font)`，
  而不是 `result_view.setFont(font)`。后者不会改变已显示或后续 `setPlainText()`/`setHtml()`
  写入文本的字体（见 `main.py` 的 `_set_font_size`）。
- 翻译结果区提示文字 `_set_result_hint()` 用 HTML，字号需跟随 `self.font_size`，不要写死。
- 全局样式表 `_APP_STYLE` 定义在 `main.py` 底部。
- 大模型 API Key 通过 keyring 存 Windows 凭据管理器，不落盘明文。

## 提交约定

- 提交信息用中文，遵循 `fix:` / `feat:` / `build:` 前缀（参考 git log）。
- `dist/PDF阅读翻译器.exe` 和 `*.spec` 是**被 git 跟踪**的（.gitignore 未忽略），
  重新打包后需一并提交。
- 注意：exe 超过 100MB 时 GitHub 会拒绝推送；若历史中混入超大 exe，
  需用 `git reset --soft` 合并/重写未推送提交来移除。
