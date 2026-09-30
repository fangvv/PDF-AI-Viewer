"""AI 阅读问答：独立浮动的对话窗口。

阅读 PDF 时随时呼出，就文中内容向大模型提问；问答边读边攒，
自动追加到与 PDF 同目录同名的 .md 笔记（见 chat_log 模块）。

界面结构：
- 顶部：标题 + 当前文件名 + 字号调节 + 「打开笔记」
- 中部：QTextBrowser 渲染的对话记录（提问右侧蓝色气泡，回答左侧卡片）
- 底部：多行输入框（Enter 发送 / Shift+Enter 换行）+ 发送/停止按钮

本窗口只是「视图」，网络请求由 main.py 的 ChatWorker 线程负责，
与 SummaryWindow 相同的分工方式。
"""

import datetime
import html
import os
import re

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QIcon, QTextDocument
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chat_log import append_exchange, load_chat_log, md_path_for
from latex_fallback import latex_to_unicode

_FONT_FAMILY = "Microsoft YaHei UI"

# 对话配色（QTextBrowser 的富文本不支持 border-radius，用色块 + 留白做区隔）
_PALETTE = {
    "light": {
        "body": "#222222",
        "meta": "#9aa0a6",
        "user_bg": "#4a90d9",
        "user_fg": "#ffffff",
        "card_bg": "#ffffff",
        "warn_bg": "#fff6e5",
        "warn": "#8a5a00",
    },
    "dark": {
        "body": "#dddddd",
        "meta": "#8a8f98",
        "user_bg": "#2f6fb5",
        "user_fg": "#f2f7ff",
        "card_bg": "#2b2b2e",
        "warn_bg": "#3a3323",
        "warn": "#d9b36a",
    },
}


# ---------- HTML 构造（模块级函数，便于脱离界面单独验证渲染效果） ----------


def _question_body(text: str, color: str, font_px: int) -> str:
    """用户提问：纯文本转义后右对齐显示。"""
    esc = html.escape(text).replace("\n", "<br>")
    return (
        f'<p align="right" style="margin:0px; color:{color}; '
        f'font-size:{font_px}px;">{esc}</p>'
    )


def _answer_body(md_text: str, color: str, font_px: int) -> str:
    """把回答里的 Markdown 渲染成 HTML 片段，并统一注入正文字号与颜色。"""
    text = latex_to_unicode(md_text or "")
    doc = QTextDocument()
    font = QFont(_FONT_FAMILY)
    font.setPixelSize(font_px)
    doc.setDefaultFont(font)
    doc.setMarkdown(text)
    source = doc.toHtml()
    match = re.search(r"<body[^>]*>(.*)</body>", source, re.S)
    body = match.group(1) if match else source
    # Qt 生成的块级元素不带 color，这里统一注入，保证夜间模式下文字可读
    body = body.replace('style="', f'style="color:{color}; ')
    return body.strip()


def _question_row(question: str, pal: dict, font_px: int, gap: int) -> str:
    return (
        f'<tr><td align="right" style="padding-top:{gap}px;">'
        f'<table cellspacing="0" cellpadding="0" align="right"><tr>'
        f'<td bgcolor="{pal["user_bg"]}" style="padding:9px 14px;">'
        f'{_question_body(question, pal["user_fg"], font_px)}'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _meta_row(text: str, pal: dict, font_px: int) -> str:
    return (
        f'<tr><td align="right" style="padding-top:5px;">'
        f'<span style="color:{pal["meta"]}; font-size:{max(11, font_px - 3)}px;">'
        f'{html.escape(text)}</span></td></tr>'
    )


def _answer_row(body_html: str, pal: dict) -> str:
    return (
        f'<tr><td bgcolor="{pal["card_bg"]}" style="padding:12px 15px;">'
        f'{body_html}</td></tr>'
    )


def _note_row(text: str, pal: dict, font_px: int) -> str:
    return (
        f'<tr><td bgcolor="{pal["warn_bg"]}" style="padding:8px 12px;">'
        f'<span style="color:{pal["warn"]}; font-size:{max(11, font_px - 3)}px;">'
        f'{html.escape(text)}</span></td></tr>'
    )


def build_history_html(exchanges, pal: dict, font_px: int,
                       pending_q: str = "", stream_text: str = "",
                       answering: bool = False, raw: str = "",
                       error_text: str = "", pal_key: str = "light") -> str:
    """把问答记录拼成一整页 HTML（交给 QTextBrowser 显示）。

    每条回答的 Markdown 只渲染一次（缓存在条目上），因为流式输出时
    本函数会被高频调用，全量重解析长历史会明显卡顿。
    """
    meta_px = max(11, font_px - 3)
    rows = []

    if raw:
        rows.append(_note_row(
            "历史记录无法逐条识别（可能手工改过格式），以下按原文渲染：", pal, font_px))
        rows.append(_answer_row(_answer_body(raw, pal["body"], font_px), pal))

    for item in exchanges:
        rows.append(_question_row(item.get("q", ""), pal, font_px, 18))
        parts = []
        if item.get("page"):
            parts.append(f"第 {item['page']} 页")
        if item.get("time"):
            parts.append(item["time"])
        if parts:
            rows.append(_meta_row(" · ".join(parts), pal, font_px))
        cache_key = (pal_key, font_px)
        if item.get("_html_key") != cache_key:
            # 回答内容写入后不再变，可安全缓存；主题/字号变了则重渲染
            item["_html"] = _answer_body(item.get("a", ""), pal["body"], font_px)
            item["_html_key"] = cache_key
        rows.append(_answer_row(item["_html"], pal))

    if answering:
        if pending_q:
            rows.append(_question_row(pending_q, pal, font_px, 18))
        if stream_text:
            body = _answer_body(stream_text, pal["body"], font_px) + (
                f'<span style="color:{pal["meta"]};">▍</span>'
            )
        else:
            body = (
                f'<p style="margin:0px; color:{pal["meta"]}; '
                f'font-size:{font_px}px;">思考中…</p>'
            )
        rows.append(_answer_row(body, pal))

    if error_text:
        rows.append(
            '<tr><td style="padding-top:6px;">'
            f'<p style="margin:0px; color:{pal["warn"]}; font-size:{font_px}px;">'
            f'{html.escape(error_text)}</p></td></tr>'
        )

    if not rows:
        rows.append(
            '<tr><td style="padding-top:36px;">'
            f'<p align="center" style="margin:0px; color:{pal["meta"]}; '
            f'font-size:{font_px}px;">有疑问就直接问吧'
            f'<br><span style="font-size:{meta_px}px;">'
            '问答会自动保存到 PDF 同目录的 .md 笔记里</span></p></td></tr>'
        )

    return (
        '<html><head><style>'
        'p, li { white-space: pre-wrap; }'
        'hr { height: 1px; border-width: 0; }'
        '</style></head>'
        f'<body style="font-family:\'{_FONT_FAMILY}\'; font-size:{font_px}px; '
        'font-weight:400; font-style:normal; margin:0px;">'
        '<table width="100%" cellspacing="0" cellpadding="0">'
        f'{"".join(rows)}</table>'
        '</body></html>'
    )


def _elide(path: str, limit: int = 24) -> str:
    """文件名过长时中间省略，避免挤爆标题栏。"""
    name = os.path.basename(path)
    if len(name) <= limit:
        return name
    keep = (limit - 1) // 2
    return f"{name[:keep]}…{name[-keep:]}"


class _ChatInput(QTextEdit):
    """多行输入框：Enter 发送，Shift+Enter 换行。"""

    sent = pyqtSignal()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.sent.emit()
            return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    """AI 阅读问答窗口（非模态，可与 PDF 阅读并行使用）。"""

    ask = pyqtSignal(str)           # 用户提交了一个问题
    stop_requested = pyqtSignal()   # 用户点了「停止」

    MIN_PX = 12
    MAX_PX = 28

    def __init__(self, parent=None, icon_path: str = ""):
        super().__init__(parent)
        self.setObjectName("chatWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("AI 阅读问答")
        self.resize(500, 660)
        self.setMinimumSize(400, 460)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.pdf_path = ""
        self.exchanges = []
        self.raw_history = ""
        self.theme = "light"
        self.font_px = 15
        self.current_page = 0
        self.answering = False
        self._pending_q = ""
        self._pending_page = 0
        self._stream_text = ""
        self._error_text = ""
        self._stopping = False

        self._build_ui()
        self._apply_style()
        self._update_buttons()
        self._render()

        # 流式输出时限频重绘（约 8 次/秒），避免每个 token 都重排整页
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render)

    # ---------- 界面 ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = QLabel("AI 阅读问答")
        self.title_label.setObjectName("chatTitle")
        header.addWidget(self.title_label)
        self.file_label = QLabel("未打开 PDF")
        self.file_label.setObjectName("chatFile")
        header.addWidget(self.file_label, 1)

        self.font_small_btn = QPushButton("A-")
        self.font_small_btn.setObjectName("chatToolBtn")
        self.font_small_btn.setFixedWidth(34)
        self.font_small_btn.setToolTip("缩小对话字号")
        self.font_small_btn.clicked.connect(lambda: self.set_font_size(self.font_px - 1))
        header.addWidget(self.font_small_btn)

        self.font_label = QLabel(str(self.font_px))
        self.font_label.setObjectName("chatFile")
        self.font_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.font_label.setFixedWidth(22)
        header.addWidget(self.font_label)

        self.font_big_btn = QPushButton("A+")
        self.font_big_btn.setObjectName("chatToolBtn")
        self.font_big_btn.setFixedWidth(34)
        self.font_big_btn.setToolTip("放大对话字号")
        self.font_big_btn.clicked.connect(lambda: self.set_font_size(self.font_px + 1))
        header.addWidget(self.font_big_btn)

        self.open_btn = QPushButton("打开笔记")
        self.open_btn.setObjectName("chatToolBtn")
        self.open_btn.setToolTip("用系统默认程序打开本篇文献的问答 .md")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_note)
        header.addWidget(self.open_btn)
        root.addLayout(header)

        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("chatView")
        self.chat_view.setOpenExternalLinks(True)
        root.addWidget(self.chat_view, 1)

        self.input = _ChatInput()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("就这篇文献提问…（Enter 发送，Shift+Enter 换行）")
        self.input.setFixedHeight(78)
        self.input.sent.connect(self._on_send)
        root.addWidget(self.input)

        bottom = QHBoxLayout()
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("chatHint")
        self.hint_label.setWordWrap(True)
        bottom.addWidget(self.hint_label, 1)

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setFixedWidth(92)
        self.send_btn.clicked.connect(self._on_send_clicked)
        bottom.addWidget(self.send_btn)
        root.addLayout(bottom)

        self._set_text_font()

    # ---------- 样式 ----------
    def _apply_style(self):
        dark = self.theme == "dark"
        bg = "#1e1f22" if dark else "#f5f6fa"
        view_border = "#3a3a3a" if dark else "#e4e6eb"
        input_bg = "#252526" if dark else "#ffffff"
        input_border = "#3a3a3a" if dark else "#d0d0d0"
        text = "#dddddd" if dark else "#222222"
        meta = "#8a8f98" if dark else "#9aa0a6"
        tool_bg = "#3a3a3a" if dark else "#ffffff"
        tool_border = "#4a4a4a" if dark else "#c8ccd0"
        tool_hover = "#4a4a4a" if dark else "#eef4fd"
        btn_disabled = "#555555" if dark else "#c0c0c0"

        self.setStyleSheet(f"""
            QWidget#chatWindow {{ background-color: {bg}; }}
            QLabel#chatTitle {{ font-size: 16px; font-weight: bold; color: {text}; }}
            QLabel#chatFile {{ font-size: 12px; color: {meta}; }}
            QLabel#chatHint {{ font-size: 12px; color: {meta}; }}
            QTextBrowser#chatView {{
                background-color: {bg};
                border: 1px solid {view_border};
                border-radius: 10px;
                padding: 4px;
            }}
            QTextEdit#chatInput {{
                background-color: {input_bg};
                border: 1px solid {input_border};
                border-radius: 10px;
                padding: 8px 10px;
                font-size: {self.font_px}px;
                color: {text};
            }}
            QTextEdit#chatInput:focus {{ border-color: #4a90d9; }}
            QPushButton#chatToolBtn {{
                background-color: {tool_bg};
                color: {text};
                border: 1px solid {tool_border};
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QPushButton#chatToolBtn:hover {{ background-color: {tool_hover}; border-color: #4a90d9; }}
            QPushButton#chatToolBtn:disabled {{ color: {meta}; background-color: {bg}; }}
            QPushButton#sendBtn {{
                background-color: #4a90d9; color: #ffffff; border: none;
                border-radius: 8px; padding: 8px 0; font-size: 14px; font-weight: bold;
            }}
            QPushButton#sendBtn:hover {{ background-color: #3a80c9; }}
            QPushButton#sendBtn:disabled {{ background-color: {btn_disabled}; }}
            QPushButton#stopBtn {{
                background-color: #e07b39; color: #ffffff; border: none;
                border-radius: 8px; padding: 8px 0; font-size: 14px; font-weight: bold;
            }}
            QPushButton#stopBtn:hover {{ background-color: #cf6c2b; }}
            QPushButton#stopBtn:disabled {{ background-color: {btn_disabled}; }}
        """)
        self._set_text_font()

    def _set_text_font(self):
        """字号同时作用于输入框与对话区（QTextEdit 必须改 document 默认字体）。"""
        font = QFont(_FONT_FAMILY)
        font.setPixelSize(self.font_px)
        self.input.setFont(font)
        self.input.document().setDefaultFont(font)
        self.chat_view.document().setDefaultFont(font)

    def set_theme(self, theme: str):
        """跟随主窗口切换日间/夜间。"""
        if theme == self.theme:
            return
        self.theme = theme
        self._apply_style()
        self._render()

    def set_font_size(self, px: int):
        px = max(self.MIN_PX, min(px, self.MAX_PX))
        if px == self.font_px:
            return
        self.font_px = px
        self.font_label.setText(str(px))
        self._apply_style()
        self._render()

    # ---------- 会话生命周期 ----------
    def load_pdf(self, pdf_path: str):
        """切到新的 PDF：读取它已有的问答笔记并显示。"""
        self.reset_session()
        self.pdf_path = pdf_path
        self.file_label.setText(_elide(pdf_path))
        self.file_label.setToolTip(pdf_path)
        exchanges, raw = load_chat_log(pdf_path)
        self.exchanges = exchanges
        self.raw_history = raw or ""
        count = len(exchanges)
        if count:
            self.set_hint(f"已载入 {count} 条历史问答")
        else:
            self.set_hint("问答将保存到 " + md_path_for(pdf_path))
        self.open_btn.setEnabled(True)
        self._update_buttons()
        self._render()

    def reset_session(self):
        """关闭 PDF / 切换文件时清空会话。"""
        self.pdf_path = ""
        self.exchanges = []
        self.raw_history = ""
        self.current_page = 0
        self.answering = False
        self._pending_q = ""
        self._pending_page = 0
        self._stream_text = ""
        self._error_text = ""
        self.file_label.setText("未打开 PDF")
        self.file_label.setToolTip("")
        self.input.clear()
        self.open_btn.setEnabled(False)
        self.set_hint("")
        self._update_buttons()
        self._render()

    def set_page(self, page: int):
        """记录当前阅读页，写进问答笔记方便日后回查。"""
        self.current_page = page

    def set_hint(self, text: str):
        self.hint_label.setText(text)

    def focus_question(self):
        """呼出窗口时直接把焦点放到输入框。"""
        self.input.setFocus()

    # ---------- 发送与回答 ----------
    def _on_send_clicked(self):
        if self.answering:
            self._stopping = True
            self.send_btn.setText("停止中…")
            self.send_btn.setEnabled(False)
            self.stop_requested.emit()
        else:
            self._on_send()

    def _on_send(self):
        if self.answering:
            return
        if not self.pdf_path:
            self.set_hint("请先打开一个 PDF 文件，再向我提问")
            return
        question = self.input.toPlainText().strip()
        if not question:
            return
        self.input.clear()
        self._pending_q = question
        self._pending_page = self.current_page
        self._stream_text = ""
        self._error_text = ""
        self.ask.emit(question)

    def begin_answer(self):
        """进入回答状态（主窗口已启动后台线程）。"""
        self.answering = True
        self._stream_text = ""
        self._error_text = ""
        self.send_btn.setEnabled(True)
        self._update_buttons()
        self.set_hint("回答中…")
        self._render()

    def append_chunk(self, piece: str):
        if not self.answering or not piece:
            return
        self._stream_text += piece
        if not self._render_timer.isActive():
            self._render_timer.start()

    def finish_answer(self, answer: str, stopped: bool = False):
        """回答结束：写入历史、追加到 .md 笔记。"""
        # 会话已被重置（中途关闭/切换了 PDF）→ 丢弃迟到的回答，不污染新会话
        if not self.answering and not self._pending_q:
            return
        question = self._pending_q
        self.answering = False
        self._pending_q = ""
        self.send_btn.setEnabled(True)
        self._update_buttons()

        text = (answer or "").strip()
        if stopped and text:
            text += "\n\n（回答中断）"
        if not text:
            # 没有有效内容（例如被立即停止）→ 不入历史，避免笔记出现空条目
            self._stream_text = ""
            self._render()
            return

        self.exchanges.append({
            "q": question,
            "a": text,
            "page": self._pending_page,
            "time": _now(),
        })
        self._stream_text = ""
        self._render()
        self._persist(question, text)

    def show_answer_error(self, message: str):
        """回答失败：只显示不写入笔记，避免污染笔记文件。"""
        if not self.answering:
            return
        self.answering = False
        self._pending_q = ""
        self._stream_text = ""
        self._error_text = message
        self.send_btn.setEnabled(True)
        self._update_buttons()
        self.set_hint("回答失败")
        self._render()

    def _persist(self, question: str, answer: str):
        if not self.pdf_path:
            return
        path, error = append_exchange(self.pdf_path, question, answer,
                                      self._pending_page)
        if error:
            self.set_hint(error)
        elif path:
            self.set_hint(f"已保存 {len(self.exchanges)} 条问答到 {path}")
            self.open_btn.setEnabled(True)

    def _update_buttons(self):
        """回答中按钮变「停止」（橙色），平时为「发送」（蓝色）。

        改 objectName 后必须 unpolish/polish，否则Qt 不会重新套用新样式。
        """
        self.send_btn.setObjectName("stopBtn" if self.answering else "sendBtn")
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)
        if self.answering:
            self.send_btn.setText("停止中…" if self._stopping else "停止")
            self.send_btn.setEnabled(not self._stopping)
        else:
            self.send_btn.setText("发送")
            # 未打开 PDF 时禁用发送（输入框也同步禁用，避免问了没处存）
            self.send_btn.setEnabled(bool(self.pdf_path))
            self.input.setEnabled(bool(self.pdf_path))
            self._stopping = False

    def _render(self):
        pal = _PALETTE.get(self.theme, _PALETTE["light"])
        html_text = build_history_html(
            self.exchanges, pal, self.font_px,
            pending_q=self._pending_q,
            stream_text=self._stream_text,
            answering=self.answering,
            raw=self.raw_history,
            error_text=self._error_text,
            pal_key=self.theme,
        )
        bar = self.chat_view.verticalScrollBar()
        was_bottom = bar.value() >= bar.maximum() - 24
        old = bar.value()
        self.chat_view.setHtml(html_text)
        if self.answering or was_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old, bar.maximum()))

    def _open_note(self):
        if not self.pdf_path:
            return
        path = md_path_for(self.pdf_path)
        if not os.path.exists(path):
            self.set_hint("还没有问答记录，先问一个问题试试")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
