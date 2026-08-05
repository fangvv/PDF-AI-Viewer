"""主窗口：左右分栏 PDF 阅读翻译器。

左侧：PDF 阅读面板（可刷选文本）
右侧：翻译结果面板
中间：可拖拽分隔条
"""

import os
import sys
import webbrowser

from PyQt6.QtCore import Qt, QThread, QTimer, QByteArray, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence, QShortcut, QIcon, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QSlider,
    QComboBox,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QToolBar,
    QStatusBar,
    QMenu,
    QProgressDialog,
)

from pdf_viewer import PdfViewer
from translator import Translator, TranslationError
import settings


class TranslateWorker(QThread):
    """后台翻译线程，避免阻塞界面。"""

    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, translator: Translator, text: str, engine: str = "auto",
                 parent=None):
        super().__init__(parent)
        self.translator = translator
        self.text = text
        self.engine = engine

    def run(self):
        try:
            result = self.translator.translate(self.text, engine=self.engine)
            self.finished.emit(result)
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SummarizeWorker(QThread):
    """后台 AI 总结线程，流式输出，避免阻塞界面。"""

    chunk = pyqtSignal(str)      # 每收到一块内容
    finished = pyqtSignal(str)   # 全部完成，携带完整结果
    failed = pyqtSignal(str)

    def __init__(self, translator: Translator, text: str, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.text = text

    def run(self):
        parts = []
        try:
            for piece in self.translator.summarize_stream(self.text):
                if piece:
                    parts.append(piece)
                    self.chunk.emit(piece)
            self.finished.emit("".join(parts))
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SummaryWindow(QWidget):
    """AI 总结独立窗口，可缩放、可滚动显示长总结。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 总结")
        self.resize(520, 620)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # 标题栏
        header = QHBoxLayout()
        title = QLabel("AI 总结")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        # 总结内容（可滚动，支持 Markdown 渲染）
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view, 1)

        # 状态提示
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

    def set_loading(self):
        """显示加载状态。"""
        self._accumulated = ""
        self.text_view.setPlainText("正在生成总结，请稍候...")
        self.status_label.setText("正在生成总结，请稍候...")

    def append_chunk(self, piece: str):
        """流式追加一块内容。

        流式阶段用 QTextCursor 增量插入纯文本，避免每次 setMarkdown 全量重解析
        导致界面卡顿；最终结果在 show_result 里一次性做 Markdown 渲染。
        """
        self._accumulated += piece
        # 若当前还是占位提示，先清空
        if self.text_view.toPlainText() == "正在生成总结，请稍候...":
            self.text_view.clear()
            self.status_label.setText("正在输出中...")
        cursor = self.text_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(piece)
        self.text_view.setTextCursor(cursor)
        # 滚动到底部
        sb = self.text_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def show_result(self, text: str):
        """显示总结结果（支持 Markdown 渲染）。"""
        if not text or not text.strip():
            self.text_view.setPlainText("（无总结结果）")
        else:
            text = self._latex_to_unicode(text)
            try:
                self.text_view.setMarkdown(text)
            except Exception:  # noqa: BLE001
                self.text_view.setPlainText(text)
        self.status_label.setText("")
        self.text_view.update()

    @staticmethod
    def _latex_to_unicode(text: str) -> str:
        """把常见的 LaTeX 数学公式转成可读的 Unicode 纯文本（兜底处理）。

        主要处理行内/块级公式定界符与常用命令，避免显示成原始 LaTeX 代码。
        """
        import re
        # 去掉公式定界符：$$...$$、$...$、\(...\)、\[...\]
        text = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.S)
        text = re.sub(r"\$(.+?)\$", r"\1", text, flags=re.S)
        text = re.sub(r"\\\[(.+?)\\\]", r"\1", text, flags=re.S)
        text = re.sub(r"\\\((.+?)\\\)", r"\1", text, flags=re.S)
        # 常用 LaTeX 命令 → Unicode
        replacements = {
            r"\times": "×", r"\cdot": "·", r"\pm": "±", r"\mp": "∓",
            r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
            r"\infty": "∞", r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
            r"\delta": "δ", r"\epsilon": "ε", r"\theta": "θ",
            r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω",
            r"\pi": "π", r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
            r"\sqrt": "√", r"\partial": "∂", r"\nabla": "∇",
            r"\rightarrow": "→", r"\leftarrow": "←", r"\in": "∈",
            r"\notin": "∉", r"\subset": "⊂", r"\subseteq": "⊆",
            r"\cup": "∪", r"\cap": "∩", r"\forall": "∀", r"\exists": "∃",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        # 上标：^{...} → Unicode 上标（仅数字/常见字母）
        sup_map = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
                   "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
                   "+": "⁺", "-": "⁻", "n": "ⁿ", "i": "ⁱ"}
        def _sup(m):
            inner = m.group(1)
            return "".join(sup_map.get(c, c) for c in inner)
        text = re.sub(r"\^\{([^{}]+)\}", _sup, text)
        text = re.sub(r"\^([0-9+\-ni])", lambda m: sup_map.get(m.group(1), m.group(1)), text)
        # 下标：_{...} → Unicode 下标（仅数字）
        sub_map = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
                   "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
                   "+": "₊", "-": "₋", "i": "ᵢ", "n": "ₙ"}
        def _sub(m):
            inner = m.group(1)
            return "".join(sub_map.get(c, c) for c in inner)
        text = re.sub(r"_\{([^{}]+)\}", _sub, text)
        text = re.sub(r"_([0-9+\-in])", lambda m: sub_map.get(m.group(1), m.group(1)), text)
        # 分数：\frac{a}{b} → (a)/(b)
        text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
        # 清理残留的反斜杠命令（保留未知命令原样，避免误删）
        return text

    def show_error(self, error: str):
        """显示错误信息。"""
        self.text_view.setPlainText(f"总结失败：\n{error}")
        self.status_label.setText("")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 阅读翻译器")
        self.resize(1200, 800)
        # 支持拖拽 PDF 文件到窗口打开
        self.setAcceptDrops(True)
        # 设置窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.translator = Translator(
            llm_key=settings.get_llm_key(),
            llm_base_url=settings.get_llm_base_url(),
            llm_model=settings.get_llm_model(),
        )
        self.current_pdf = None
        self.worker = None
        self.font_size = 14
        self.theme = "light"  # 主题：light / dark
        # 搜索状态
        self._search_results = []
        self._search_index = -1
        self._last_search_text = ""

        # 窗口状态防抖保存（resize/move 后延迟写入，避免频繁写文件）
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_window_state)

        self._build_ui()
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_settings()
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """设置全局快捷键。"""
        # Ctrl + = / Ctrl + + 放大 PDF
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self._zoom_pdf(1))
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self._zoom_pdf(1))
        # Ctrl + - 缩小 PDF
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._zoom_pdf(-1))
        # Ctrl + L 切换全屏
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._toggle_fullscreen)

    def _zoom_pdf(self, delta: int):
        """用快捷键调节 PDF 缩放比例。"""
        # 切换到百分比模式
        self.zoom_mode.setCurrentIndex(2)
        step = 10
        new_value = self.zoom_slider.value() + delta * step
        new_value = max(self.zoom_slider.minimum(), min(new_value, self.zoom_slider.maximum()))
        self.zoom_slider.setValue(new_value)

    def _toggle_fullscreen(self):
        """切换全屏/窗口模式。"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ---------- UI ----------
    def _build_ui(self):
        # 左侧 PDF 阅读器
        self.viewer = PdfViewer()
        self.viewer.pageChanged.connect(self._on_page_changed)
        self.viewer.textSelected.connect(self._on_text_selected)
        self.viewer.textSelectedAt.connect(self._on_text_selected_at)
        self.viewer.linkClicked.connect(self._on_link_clicked)
        self.viewer.internalLinkClicked.connect(self._on_internal_link_clicked)
        self.viewer.zoomChanged.connect(self._on_viewer_zoom_changed)

        # 浮动翻译按钮（刷选文本后出现在鼠标附近）
        self.float_btn = QPushButton("翻译")
        self.float_btn.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        )
        self.float_btn.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.float_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2d7ff9; color: white; border: none;"
            "  border-radius: 4px; padding: 6px 14px; font-size: 13px;"
            "}"
            "QPushButton:hover { background-color: #1f6fe0; }"
        )
        self.float_btn.adjustSize()
        self.float_btn.hide()
        self.float_btn.clicked.connect(self._translate_current)

        # AI 总结独立窗口
        self.summary_window = SummaryWindow(self)

        # 右侧翻译面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)

        title = QLabel("翻译结果")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(title)

        # 字体调节栏
        font_bar = QHBoxLayout()
        font_bar.addWidget(QLabel("字体大小"))
        self.font_small_btn = QPushButton("A-")
        self.font_small_btn.setFixedWidth(40)
        self.font_small_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #ffffff; color: #333333;"
            "  border: 1px solid #c0c0c0; border-radius: 4px;"
            "  padding: 2px 0; font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #e8f0fe; border-color: #4a90d9; }"
            "QPushButton:pressed { background-color: #d0e0f5; }"
        )
        self.font_small_btn.clicked.connect(lambda: self._adjust_font(-1))
        font_bar.addWidget(self.font_small_btn)
        self.font_big_btn = QPushButton("A+")
        self.font_big_btn.setFixedWidth(40)
        self.font_big_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #ffffff; color: #333333;"
            "  border: 1px solid #c0c0c0; border-radius: 4px;"
            "  padding: 2px 0; font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #e8f0fe; border-color: #4a90d9; }"
            "QPushButton:pressed { background-color: #d0e0f5; }"
        )
        self.font_big_btn.clicked.connect(lambda: self._adjust_font(1))
        font_bar.addWidget(self.font_big_btn)
        self.font_size_label = QLabel("14")
        font_bar.addWidget(self.font_size_label)
        font_bar.addStretch(1)
        right_layout.addLayout(font_bar)

        # 翻译引擎选择
        engine_bar = QHBoxLayout()
        engine_bar.addWidget(QLabel("翻译引擎"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("自动（推荐）", "auto")
        for name in self.translator.engine_names():
            self.engine_combo.addItem(name, name)
        engine_bar.addWidget(self.engine_combo, 1)
        right_layout.addLayout(engine_bar)

        self.translate_btn = QPushButton("翻译选中内容")
        self.translate_btn.setEnabled(False)
        self.translate_btn.clicked.connect(self._translate_current)
        right_layout.addWidget(self.translate_btn)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self._set_result_hint()
        right_layout.addWidget(self.result_view, 1)

        # 分栏
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.viewer)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([700, 500])
        self.setCentralWidget(self.splitter)

    def _build_menubar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        open_action = QAction("打开 PDF...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(open_action)

        # 最近打开子菜单
        self.recent_menu = file_menu.addMenu("最近打开")
        self._update_recent_menu()

        file_menu.addSeparator()
        close_action = QAction("关闭 PDF", self)
        close_action.triggered.connect(self.close_pdf)
        file_menu.addAction(close_action)

        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 设置菜单
        settings_menu = menubar.addMenu("设置")
        llm_action = QAction("大模型设置...", self)
        llm_action.triggered.connect(self._configure_llm)
        settings_menu.addAction(llm_action)
        settings_menu.addSeparator()
        # 主题子菜单（日间 / 夜间）
        theme_menu = settings_menu.addMenu("主题")
        self.theme_actions = {}
        for key, label in (("light", "日间"), ("dark", "夜间")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self._set_theme(k))
            theme_menu.addAction(act)
            self.theme_actions[key] = act
        self.theme_actions["light"].setChecked(True)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        website_action = QAction("官网", self)
        website_action.triggered.connect(
            lambda: webbrowser.open("https://github.com/fangvv/PDF-AI-Viewer")
        )
        help_menu.addAction(website_action)
        help_menu.addSeparator()
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        """显示关于对话框。"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
        from PyQt6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle("关于 PDF 阅读翻译器")
        dlg.setFixedWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # Logo
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        logo_label = QLabel()
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(
                96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(pixmap)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        # 标题
        title = QLabel("PDF 阅读翻译器")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # 版本
        version = QLabel("版本 1.0.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #888;")
        layout.addWidget(version)

        # 简介
        desc = QLabel(
            "一个类似「知云文献翻译」的桌面 PDF 阅读翻译工具。\n"
            "左侧查看 PDF，右侧显示翻译结果；\n"
            "用鼠标刷选内容即可翻译，支持记录阅读位置。"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555;")
        layout.addWidget(desc)

        # 官网
        website = QLabel(
            '<a href="https://github.com/fangvv/PDF-AI-Viewer" style="color:#2d7ff9;">'
            '官网：github.com/fangvv/PDF-AI-Viewer</a>'
        )
        website.setAlignment(Qt.AlignmentFlag.AlignCenter)
        website.setOpenExternalLinks(True)
        layout.addWidget(website)

        # 联系方式
        contact = QLabel(
            '<a href="mailto:fangvv@qq.com" style="color:#2d7ff9;">'
            '联系我：fangvv@qq.com</a>'
        )
        contact.setAlignment(Qt.AlignmentFlag.AlignCenter)
        contact.setOpenExternalLinks(True)
        layout.addWidget(contact)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    def _configure_llm(self):
        """配置大模型（OpenAI 兼容接口）。"""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QComboBox, QPushButton, QMessageBox,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("大模型设置")
        dlg.setFixedWidth(480)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        # 接口地址
        layout.addWidget(QLabel("接口地址 (Base URL)"))
        base_url_edit = QLineEdit(settings.get_llm_base_url())
        base_url_edit.setPlaceholderText("例如 https://api.openai.com/v1 或 https://api.siliconflow.cn/v1")
        layout.addWidget(base_url_edit)

        # API Key
        layout.addWidget(QLabel("API Key"))
        key_edit = QLineEdit(settings.get_llm_key())
        key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_edit.setPlaceholderText("sk-...")
        layout.addWidget(key_edit)

        # 模型名（下拉框 + 刷新按钮）
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("模型"))
        self._llm_model_combo = QComboBox()
        self._llm_model_combo.setEditable(True)
        current_model = settings.get_llm_model()
        if current_model:
            self._llm_model_combo.addItem(current_model)
        model_row.addWidget(self._llm_model_combo, 1)
        refresh_btn = QPushButton("刷新模型")
        refresh_btn.clicked.connect(
            lambda: self._refresh_llm_models(base_url_edit.text().strip(),
                                             key_edit.text().strip())
        )
        model_row.addWidget(refresh_btn)
        layout.addLayout(model_row)

        # 提示
        hint = QLabel("支持任意 OpenAI 兼容服务商（OpenAI、DeepSeek、智谱、硅基流动、本地 Ollama 等）。\n"
                      "点击「刷新模型」从服务商拉取可用模型列表。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        # 按钮（Windows 习惯：确定在左、取消在右）
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        if dlg.exec():
            base_url = base_url_edit.text().strip()
            key = key_edit.text().strip()
            model = self._llm_model_combo.currentText().strip()
            settings.save_llm_key(key)
            settings.save_llm_config(base_url, model)
            self.translator.configure_llm(key, base_url, model)
            self.status.showMessage("大模型设置已保存")

    def _refresh_llm_models(self, base_url: str, api_key: str):
        """从服务商拉取模型列表并填充下拉框。"""
        from PyQt6.QtWidgets import QMessageBox
        if not base_url:
            QMessageBox.warning(self, "提示", "请先填写接口地址")
            return
        try:
            # 临时用当前输入配置拉取模型
            self.translator.configure_llm(api_key, base_url, "")
            models = self.translator.list_llm_models()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "拉取失败", f"无法获取模型列表：\n{exc}")
            return
        self._llm_model_combo.clear()
        for m in models:
            self._llm_model_combo.addItem(m)
        self.status.showMessage(f"已获取 {len(models)} 个模型")

    def _update_recent_menu(self):
        """刷新最近打开菜单。"""
        self.recent_menu.clear()
        recent = settings.load_recent()
        if not recent:
            empty = self.recent_menu.addAction("（无）")
            empty.setEnabled(False)
            return
        for path in recent:
            name = os.path.basename(path)
            action = self.recent_menu.addAction(name)
            action.setToolTip(path)
            action.triggered.connect(
                lambda checked=False, p=path: self._open_recent(p)
            )
        # 清空历史记录
        self.recent_menu.addSeparator()
        clear_action = self.recent_menu.addAction("清空历史记录")
        clear_action.triggered.connect(self._clear_recent)

    def _clear_recent(self):
        """清空最近打开历史。"""
        reply = QMessageBox.question(
            self, "清空历史记录", "确定要清空所有最近打开记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            settings.clear_recent()
            self._update_recent_menu()
            self.status.showMessage("已清空历史记录")

    def _open_recent(self, path: str):
        if os.path.exists(path):
            self.load_pdf(path)
        else:
            QMessageBox.warning(self, "文件不存在", f"文件不存在或已被移动：\n{path}")
            # 从历史中移除失效文件
            settings.remove_recent(path)
            self._update_recent_menu()

    def _build_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("打开 PDF", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        close_action = QAction("关闭 PDF", self)
        close_action.triggered.connect(self.close_pdf)
        close_action.setEnabled(False)
        toolbar.addAction(close_action)
        self.close_action = close_action

        toolbar.addSeparator()

        # AI 总结（整篇文档）
        summary_action = QAction("全文总结", self)
        summary_action.triggered.connect(self._summarize_current)
        summary_action.setEnabled(False)
        toolbar.addAction(summary_action)
        self.summary_action = summary_action

        toolbar.addSeparator()

        # 页码导航
        self.page_label = QLabel("")
        self.page_label.setEnabled(False)
        toolbar.addWidget(self.page_label)

        self.page_prefix_label = QLabel("跳转到第")
        self.page_prefix_label.setEnabled(False)
        toolbar.addWidget(self.page_prefix_label)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(0)
        self.page_spin.setMaximum(1)
        self.page_spin.setValue(0)
        self.page_spin.setFixedWidth(60)
        self.page_spin.setEnabled(False)
        self.page_spin.valueChanged.connect(self._on_spin_changed)
        toolbar.addWidget(self.page_spin)
        self.page_suffix_label = QLabel("页")
        self.page_suffix_label.setEnabled(False)
        toolbar.addWidget(self.page_suffix_label)

        toolbar.addSeparator()

        # 全文搜索
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索...")
        self.search_edit.setFixedWidth(160)
        self.search_edit.returnPressed.connect(self._do_search)
        toolbar.addWidget(self.search_edit)

        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._do_search)
        toolbar.addWidget(search_btn)

        self.search_prev_btn = QPushButton("上一个")
        self.search_prev_btn.clicked.connect(lambda: self._goto_search(-1))
        self.search_prev_btn.setEnabled(False)
        toolbar.addWidget(self.search_prev_btn)

        self.search_next_btn = QPushButton("下一个")
        self.search_next_btn.clicked.connect(lambda: self._goto_search(1))
        self.search_next_btn.setEnabled(False)
        toolbar.addWidget(self.search_next_btn)

        self.search_count_label = QLabel("")
        toolbar.addWidget(self.search_count_label)

        toolbar.addSeparator()

        # 缩放模式
        toolbar.addWidget(QLabel("缩放"))
        self.zoom_mode = QComboBox()
        self.zoom_mode.addItem("适合页面")
        self.zoom_mode.addItem("适合宽度")
        self.zoom_mode.addItem("百分比")
        self.zoom_mode.setCurrentIndex(1)  # 默认适合宽度
        self.zoom_mode.currentIndexChanged.connect(self._on_zoom_mode_changed)
        toolbar.addWidget(self.zoom_mode)

        # 百分比滑块（仅百分比模式可用）
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(150)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_slider)

        self.zoom_label = QLabel("150%")
        toolbar.addWidget(self.zoom_label)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("请打开一个 PDF 文件")

        # 右下角显示当前日期和时间
        self.datetime_label = QLabel()
        self.status.addPermanentWidget(self.datetime_label)
        self._update_datetime()
        self._datetime_timer = QTimer(self)
        self._datetime_timer.timeout.connect(self._update_datetime)
        self._datetime_timer.start(1000)  # 每秒刷新

    def _update_datetime(self):
        from datetime import datetime
        self.datetime_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ---------- 事件 ----------
    def _on_page_changed(self, page, total):
        self.page_label.setText(f"第 {page} / {total} 页")
        # 避免触发 valueChanged 循环
        self.page_spin.blockSignals(True)
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(total)
        self.page_spin.setValue(page)
        self.page_spin.blockSignals(False)

    def _on_spin_changed(self, value):
        self.viewer.go_to_page(value)

    def _do_search(self):
        """执行全文搜索。

        若搜索词与上次相同，则跳到下一个结果（相当于「下一个」）；
        若搜索词变化，则重新搜索并跳到第一个结果。
        """
        text = self.search_edit.text().strip()
        if not text or not self.current_pdf:
            return
        if text != self._last_search_text:
            # 搜索词变化：重新搜索，跳到第一个
            self._last_search_text = text
            self._search_results = self.viewer.search(text)
            self._search_index = -1
            if self._search_results:
                self.search_prev_btn.setEnabled(True)
                self.search_next_btn.setEnabled(True)
                self.search_count_label.setText(f"共 {len(self._search_results)} 处")
                self._goto_search(1)
            else:
                self.search_prev_btn.setEnabled(False)
                self.search_next_btn.setEnabled(False)
                self.search_count_label.setText("未找到")
                self.viewer.clear_search()
                self.status.showMessage(f"未找到「{text}」")
        else:
            # 搜索词未变：跳到下一个结果
            self._goto_search(1)

    def _goto_search(self, step: int):
        """跳转到下一个/上一个搜索结果。"""
        if not self._search_results:
            return
        total = len(self._search_results)
        self._search_index = (self._search_index + step) % total
        page_index, rect = self._search_results[self._search_index]
        # 滚动到对应页并让高亮矩形在视窗中垂直居中
        self.viewer.scroll_to_rect(page_index, rect)
        self.viewer.highlight_search(page_index, [rect])
        self.search_count_label.setText(
            f"{self._search_index + 1} / {total}"
        )
        self.status.showMessage(
            f"第 {page_index + 1} 页，第 {self._search_index + 1} / {total} 处"
        )

    def _on_zoom_mode_changed(self, index):
        if index == 0:  # 适合页面
            self.zoom_slider.setEnabled(False)
            self.zoom_label.setText("适合页面")
            self.viewer.fit_page()
        elif index == 1:  # 适合宽度
            self.zoom_slider.setEnabled(False)
            self.zoom_label.setText("适合宽度")
            self.viewer.fit_width()
        else:  # 百分比
            self.zoom_slider.setEnabled(True)
            # 以当前实际缩放比例作为百分比初始值
            current_pct = int(round(self.viewer.zoom * 100))
            self.zoom_slider.setValue(current_pct)
            self._on_zoom_changed(current_pct)

    def _on_zoom_changed(self, value):
        zoom = value / 100.0
        self.viewer.set_zoom(zoom)
        self.zoom_label.setText(f"{value}%")

    def _on_viewer_zoom_changed(self, zoom):
        """Ctrl+滚轮缩放后，同步工具栏的缩放模式与滑块。"""
        # 切换到百分比模式
        self.zoom_mode.setCurrentIndex(2)
        pct = int(round(zoom * 100))
        # 避免触发 valueChanged 循环
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(pct)
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{pct}%")

    def _on_text_selected(self, text):
        self._selected_text = text
        self.translate_btn.setEnabled(bool(text))
        self.status.showMessage(f"已选中 {len(text)} 个字符")

    def _on_text_selected_at(self, text, global_pos):
        """刷选文本后，在鼠标附近显示浮动翻译按钮。"""
        self._selected_text = text
        self.translate_btn.setEnabled(bool(text))
        # 把按钮放到鼠标释放位置附近（右下偏移）
        self.float_btn.adjustSize()
        x = global_pos.x() + 12
        y = global_pos.y() + 12
        # 防止超出屏幕
        screen = self.screen().availableGeometry()
        if x + self.float_btn.width() > screen.right():
            x = global_pos.x() - self.float_btn.width() - 12
        if y + self.float_btn.height() > screen.bottom():
            y = global_pos.y() - self.float_btn.height() - 12
        self.float_btn.move(x, y)
        self.float_btn.show()
        self.float_btn.raise_()

    def _on_link_clicked(self, url: str):
        """点击 PDF 链接时用系统浏览器打开。"""
        try:
            webbrowser.open(url)
            self.status.showMessage(f"已打开链接：{url}")
        except Exception as exc:  # noqa: BLE001
            self.status.showMessage(f"无法打开链接：{exc}")

    def _on_internal_link_clicked(self, page_index: int, rect):
        """点击 PDF 内部链接（如参考文献引用）时跳转到对应位置。"""
        self.viewer.go_to_internal_link(page_index, rect)
        self.status.showMessage(f"已跳转到第 {page_index + 1} 页")

    def _translate_current(self):
        text = getattr(self, "_selected_text", "")
        if not text:
            return
        engine = self.engine_combo.currentData()
        self.result_view.setPlainText("翻译中...")
        self.translate_btn.setEnabled(False)
        self.float_btn.hide()
        self.worker = TranslateWorker(self.translator, text, engine)
        self.worker.finished.connect(self._on_translate_done)
        self.worker.failed.connect(self._on_translate_failed)
        self.worker.start()

    def _on_translate_done(self, result):
        self.result_view.setPlainText(result)
        self.translate_btn.setEnabled(True)
        self.status.showMessage("翻译完成")

    def _on_translate_failed(self, error):
        self.result_view.setPlainText(f"翻译失败：\n{error}")
        self.translate_btn.setEnabled(True)
        self.status.showMessage("翻译失败")

    def _set_result_hint(self):
        """在翻译结果区显示灰色提示文字（未打开/未翻译时）。"""
        color = "#666666" if self.theme == "dark" else "#999999"
        self.result_view.setHtml(
            f'<div style="color:{color}; font-size:{self.font_size}px; line-height:1.8;">'
            "在左侧 PDF 中刷选文本，<br>"
            "点击「翻译选中内容」或按 Ctrl+T 翻译。"
            "</div>"
        )

    def _summarize_current(self):
        """对整篇文档进行 AI 总结。"""
        if not self.viewer.page_widgets:
            self.status.showMessage("请先打开一个 PDF 文件")
            return
        # 取全文（限制长度，避免超出大模型上下文）
        text = self.viewer.document_text(max_chars=60000)
        if not text.strip():
            self.status.showMessage("文档没有可总结的文本")
            return
        total_pages = len(self.viewer.page_widgets)
        # 显示总结窗口并进入加载状态
        self.summary_window.set_loading()
        self.summary_window.show()
        self.summary_window.raise_()
        self.summary_window.activateWindow()
        # 后台线程生成总结（流式输出）
        self.summary_worker = SummarizeWorker(self.translator, text)
        self.summary_worker.chunk.connect(self.summary_window.append_chunk)
        self.summary_worker.finished.connect(self._on_summary_done)
        self.summary_worker.failed.connect(self._on_summary_failed)
        self.summary_worker.start()
        self.status.showMessage(f"正在总结全文（共 {total_pages} 页）...")

    def _on_summary_done(self, result):
        self.summary_window.show_result(result)

    def _on_summary_failed(self, error):
        self.summary_window.show_error(error)

    # ---------- 文件 ----------
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF", "", "PDF 文件 (*.pdf)"
        )
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str):
        # 显示加载进度对话框
        progress = QProgressDialog("正在加载 PDF...", "取消", 0, 100, self)
        progress.setWindowTitle("加载中")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def on_progress(done, total):
            if total > 0:
                progress.setMaximum(total)
                progress.setValue(done)
                progress.setLabelText(f"正在加载 PDF...（{done}/{total} 页）")
            # 处理界面事件，让进度条刷新
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()

        try:
            self.viewer.load_document_progress(path, on_progress)
        except Exception as exc:  # noqa: BLE001
            progress.close()
            QMessageBox.critical(self, "打开失败", f"无法打开 PDF：\n{exc}")
            return
        progress.close()

        # 重置翻译相关状态
        self._selected_text = ""
        self.translate_btn.setEnabled(False)
        self.float_btn.hide()
        self._set_result_hint()

        self.current_pdf = os.path.abspath(path)
        self.setWindowTitle(f"PDF 阅读翻译器 - {os.path.basename(path)}")
        self.status.showMessage(f"已打开：{path}")
        # 启用关闭/总结按钮
        self.close_action.setEnabled(True)
        self.summary_action.setEnabled(True)
        # 启用页码导航
        self.page_label.setEnabled(True)
        self.page_prefix_label.setEnabled(True)
        self.page_spin.setEnabled(True)
        self.page_suffix_label.setEnabled(True)

        # 记录到最近打开列表
        settings.add_recent(self.current_pdf)
        self._update_recent_menu()

        # 应用当前缩放模式（默认适合宽度）
        self._on_zoom_mode_changed(self.zoom_mode.currentIndex())

        # 恢复阅读位置
        pos = settings.get_position(self.current_pdf)
        if pos:
            self.viewer.go_to_page(pos.get("page", 1))
            self.status.showMessage(f"已恢复到第 {pos.get('page', 1)} 页")

    def close_pdf(self):
        """关闭当前 PDF。"""
        if not self.current_pdf:
            self.status.showMessage("当前没有打开的 PDF")
            return
        # 记录阅读位置
        settings.save_position(
            self.current_pdf,
            self.viewer.current_page(),
            self.viewer.verticalScrollBar().value(),
        )
        self.viewer.clear_document()
        self.current_pdf = None
        self.setWindowTitle("PDF 阅读翻译器")
        # 禁用关闭/总结按钮
        self.close_action.setEnabled(False)
        self.summary_action.setEnabled(False)
        # 禁用页码导航
        self.page_label.setEnabled(False)
        self.page_prefix_label.setEnabled(False)
        self.page_spin.setEnabled(False)
        self.page_suffix_label.setEnabled(False)
        # 重置页码显示（避免残留"1"）
        self.page_label.setText("")
        self.page_spin.blockSignals(True)
        self.page_spin.setMinimum(0)
        self.page_spin.setMaximum(1)
        self.page_spin.setValue(0)
        self.page_spin.blockSignals(False)
        # 重置翻译相关状态
        self._selected_text = ""
        self.translate_btn.setEnabled(False)
        self.float_btn.hide()
        self._set_result_hint()
        self.status.showMessage("已关闭 PDF")

    # ---------- 设置 ----------
    def _set_theme(self, theme: str):
        """切换主题（light/dark）。"""
        self.theme = theme
        # 更新菜单勾选状态
        for key, act in self.theme_actions.items():
            act.setChecked(key == theme)
        # 应用对应全局样式表
        style = {
            "light": _APP_STYLE,
            "dark": _APP_STYLE_DARK,
        }[theme]
        QApplication.instance().setStyleSheet(style)
        # 更新硬编码颜色的控件
        self._apply_theme_to_widgets()
        # 保存设置
        s = settings.load_settings()
        s["theme"] = theme
        settings.save_settings(s)

    def _apply_theme_to_widgets(self):
        """更新带硬编码颜色的控件，使其适配当前主题。"""
        theme = self.theme
        # 浮动翻译按钮（各主题下保持蓝色，便于识别）
        self.float_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2d7ff9; color: white; border: none;"
            "  border-radius: 4px; padding: 6px 14px; font-size: 13px;"
            "}"
            "QPushButton:hover { background-color: #1f6fe0; }"
        )
        # 字体调节按钮（A- / A+）两态样式
        if theme == "dark":
            btn_style = (
                "QPushButton {"
                "  background-color: #3a3a3a; color: #cccccc;"
                "  border: 1px solid #4a4a4a; border-radius: 4px;"
                "  padding: 2px 0; font-size: 14px; font-weight: bold;"
                "}"
                "QPushButton:hover { background-color: #4a4a4a; border-color: #4a90d9; }"
                "QPushButton:pressed { background-color: #555555; }"
            )
        else:
            btn_style = (
                "QPushButton {"
                "  background-color: #ffffff; color: #333333;"
                "  border: 1px solid #c0c0c0; border-radius: 4px;"
                "  padding: 2px 0; font-size: 14px; font-weight: bold;"
                "}"
                "QPushButton:hover { background-color: #e8f0fe; border-color: #4a90d9; }"
                "QPushButton:pressed { background-color: #d0e0f5; }"
            )
        self.font_small_btn.setStyleSheet(btn_style)
        self.font_big_btn.setStyleSheet(btn_style)
        # 翻译结果提示文字颜色
        self._set_result_hint()
        # PDF 阅读区空状态提示 + 页面主题
        self.viewer.set_empty_style(theme)
        self.viewer.set_theme(theme)

    def _restore_settings(self):
        s = settings.load_settings()
        # 恢复主题（兼容旧的 dark_mode 配置）
        theme = s.get("theme")
        if not theme and s.get("dark_mode"):
            theme = "dark"
        if theme in ("light", "dark"):
            self._set_theme(theme)
        sizes = s.get("splitter_sizes")
        if sizes and len(sizes) == 2:
            self.splitter.setSizes(sizes)
        font_size = s.get("font_size")
        if font_size:
            self._set_font_size(font_size)
        # 恢复窗口几何与最大化状态（延迟到窗口显示后生效）
        geometry = s.get("window_geometry")
        if geometry:
            try:
                self.restoreGeometry(QByteArray(bytes.fromhex(geometry)))
            except (ValueError, TypeError):
                pass
        if s.get("window_maximized"):
            QTimer.singleShot(0, self.showMaximized)

    def _save_settings(self):
        # 先读取已有配置，避免覆盖掉大模型设置（llm_base_url / llm_model）
        s = settings.load_settings()
        s["splitter_sizes"] = self.splitter.sizes()
        s["font_size"] = self.font_size
        settings.save_settings(s)

    def _save_window_state(self):
        """保存窗口几何与最大化状态。"""
        s = settings.load_settings()
        s["window_geometry"] = bytes(self.saveGeometry()).hex()
        s["window_maximized"] = self.isMaximized()
        settings.save_settings(s)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._save_timer.start()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._save_timer.start()

    def _adjust_font(self, delta: int):
        """调整翻译字体大小。"""
        self._set_font_size(self.font_size + delta)

    def _set_font_size(self, size: int):
        """设置翻译字体大小。"""
        size = max(8, min(size, 40))
        self.font_size = size
        font = self.result_view.font()
        font.setPointSize(size)
        # 必须设置到 document 上，setFont() 不会改变已显示/后续 setPlainText 的字体
        self.result_view.document().setDefaultFont(font)
        self.font_size_label.setText(str(size))

    # ---------- 拖拽打开 ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.load_pdf(url.toLocalFile())
                event.acceptProposedAction()
                return

    # ---------- 关闭 ----------
    def closeEvent(self, event):
        # 自动记录阅读位置
        if self.current_pdf:
            settings.save_position(
                self.current_pdf,
                self.viewer.current_page(),
                self.viewer.verticalScrollBar().value(),
            )
        self._save_settings()
        self._save_window_state()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDFTranslator")
    # 设置应用图标（任务栏）
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    # 设置全局字体（微软雅黑，中文显示更美观）
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)
    app.setStyleSheet(_APP_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


# 全局样式表：现代简洁风格
_APP_STYLE = """
QMainWindow {
    background-color: #f5f6fa;
}
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px;
    spacing: 6px;
}
QToolBar QLabel {
    color: #333333;
    font-size: 13px;
    font-weight: 500;
}
QToolButton {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 10px;
    color: #333333;
    font-size: 13px;
}
QToolButton:hover {
    background-color: #e8f0fe;
    border-color: #4a90d9;
}
QToolButton:disabled {
    background-color: #f0f0f0;
    border-color: #e0e0e0;
    color: #b0b0b0;
}
/* 工具栏内的按钮（搜索/上一个/下一个）与 QToolButton 风格统一 */
QToolBar QPushButton {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 10px;
    color: #333333;
    font-size: 13px;
}
QToolBar QPushButton:hover {
    background-color: #e8f0fe;
    border-color: #4a90d9;
}
QToolBar QPushButton:disabled {
    background-color: #f0f0f0;
    border-color: #e0e0e0;
    color: #b0b0b0;
}
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
    font-size: 13px;
}
QMenuBar::item {
    padding: 5px 10px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: #e8f0fe;
    border-radius: 4px;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    padding: 4px;
    font-size: 13px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #e8f0fe;
}
QPushButton {
    background-color: #4a90d9;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #3a80c9;
}
QPushButton:disabled {
    background-color: #c0c0c0;
}
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 8px;
    font-size: 14px;
    color: #222222;
}
QScrollArea {
    background-color: #e8e8e8;
    border: none;
}
QScrollBar:vertical {
    background: #f0f0f0;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c0c0c0;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 22px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #d0d0d0;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #4a90d9;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e0e0e0;
    color: #666666;
}
QSplitter::handle {
    background-color: #d0d0d0;
    width: 3px;
}
QSplitter::handle:hover {
    background-color: #4a90d9;
}
"""


# 夜间模式样式表
_APP_STYLE_DARK = """
QMainWindow {
    background-color: #1e1e1e;
}
QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #3a3a3a;
    padding: 4px;
    spacing: 6px;
}
QToolBar QLabel {
    color: #cccccc;
    font-size: 13px;
    font-weight: 500;
}
QToolButton {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 4px 10px;
    color: #cccccc;
    font-size: 13px;
}
QToolButton:hover {
    background-color: #4a4a4a;
    border-color: #4a90d9;
}
QToolButton:disabled {
    background-color: #2d2d2d;
    border-color: #3a3a3a;
    color: #666666;
}
/* 工具栏内的按钮（搜索/上一个/下一个）与 QToolButton 风格统一 */
QToolBar QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 4px 10px;
    color: #cccccc;
    font-size: 13px;
}
QToolBar QPushButton:hover {
    background-color: #4a4a4a;
    border-color: #4a90d9;
}
QToolBar QPushButton:disabled {
    background-color: #2d2d2d;
    border-color: #3a3a3a;
    color: #666666;
}
QMenuBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #3a3a3a;
    font-size: 13px;
}
QMenuBar::item {
    padding: 5px 10px;
    background: transparent;
    color: #cccccc;
}
QMenuBar::item:selected {
    background-color: #4a4a4a;
    border-radius: 4px;
}
QMenu {
    background-color: #2d2d2d;
    border: 1px solid #4a4a4a;
    padding: 4px;
    font-size: 13px;
    color: #cccccc;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #4a4a4a;
}
QPushButton {
    background-color: #4a90d9;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #3a80c9;
}
QPushButton:disabled {
    background-color: #555555;
}
QTextEdit {
    background-color: #252526;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 8px;
    font-size: 14px;
    color: #dddddd;
}
QScrollArea {
    background-color: #2b2b2b;
    border: none;
}
QScrollBar:vertical {
    background: #2d2d2d;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #555555;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #666666;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSpinBox, QComboBox {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 22px;
    color: #cccccc;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #cccccc;
    selection-background-color: #4a4a4a;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #4a4a4a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #4a90d9;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QStatusBar {
    background-color: #2d2d2d;
    border-top: 1px solid #3a3a3a;
    color: #999999;
}
QSplitter::handle {
    background-color: #3a3a3a;
    width: 3px;
}
QSplitter::handle:hover {
    background-color: #4a90d9;
}
"""


if __name__ == "__main__":
    main()
