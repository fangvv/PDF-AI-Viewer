"""主窗口：左右分栏 PDF 阅读翻译器。

左侧：PDF 阅读面板（可刷选文本）
右侧：翻译结果面板
中间：可拖拽分隔条
"""

import os
import sys
import webbrowser

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence, QShortcut, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
        self.status_label.setText("")

    def append_chunk(self, piece: str):
        """流式追加一块内容。"""
        self._accumulated += piece
        try:
            self.text_view.setMarkdown(self._accumulated)
        except Exception:  # noqa: BLE001
            self.text_view.setPlainText(self._accumulated)
        # 滚动到底部
        sb = self.text_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.text_view.update()

    def show_result(self, text: str):
        """显示总结结果（支持 Markdown 渲染）。"""
        if not text or not text.strip():
            self.text_view.setPlainText("（无总结结果）")
        else:
            try:
                self.text_view.setMarkdown(text)
            except Exception:  # noqa: BLE001
                self.text_view.setPlainText(text)
        self.status_label.setText("")
        self.text_view.update()

    def show_error(self, error: str):
        """显示错误信息。"""
        self.text_view.setPlainText(f"总结失败：\n{error}")
        self.status_label.setText("")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 阅读翻译器")
        self.resize(1200, 800)
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

        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
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
        toolbar.addAction(close_action)

        toolbar.addSeparator()

        # AI 总结（对当前页）
        summary_action = QAction("AI 总结", self)
        summary_action.triggered.connect(self._summarize_current)
        toolbar.addAction(summary_action)

        toolbar.addSeparator()

        # 页码导航
        self.page_label = QLabel("第 1 / 1 页")
        toolbar.addWidget(self.page_label)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setPrefix("跳转到第 ")
        self.page_spin.setSuffix(" 页")
        self.page_spin.valueChanged.connect(self._on_spin_changed)
        toolbar.addWidget(self.page_spin)

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
        self.page_spin.setMaximum(total)
        self.page_spin.setValue(page)
        self.page_spin.blockSignals(False)

    def _on_spin_changed(self, value):
        self.viewer.go_to_page(value)

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
        self.result_view.setHtml(
            f'<div style="color:#999999; font-size:{self.font_size}px; line-height:1.8;">'
            "在左侧 PDF 中刷选文本，<br>"
            "点击「翻译选中内容」或按 Ctrl+T 翻译。"
            "</div>"
        )

    def _summarize_current(self):
        """对当前页进行 AI 总结。"""
        if not self.viewer.page_widgets:
            self.status.showMessage("请先打开一个 PDF 文件")
            return
        text = self.viewer.current_page_text()
        if not text.strip():
            self.status.showMessage("当前页没有可总结的文本")
            return
        page = self.viewer.current_page()
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
        self.status.showMessage(f"正在总结第 {page} 页...")

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
        # 重置翻译相关状态
        self._selected_text = ""
        self.translate_btn.setEnabled(False)
        self.float_btn.hide()
        self._set_result_hint()
        self.status.showMessage("已关闭 PDF")

    # ---------- 设置 ----------
    def _restore_settings(self):
        s = settings.load_settings()
        sizes = s.get("splitter_sizes")
        if sizes and len(sizes) == 2:
            self.splitter.setSizes(sizes)
        font_size = s.get("font_size")
        if font_size:
            self._set_font_size(font_size)

    def _save_settings(self):
        # 先读取已有配置，避免覆盖掉大模型设置（llm_base_url / llm_model）
        s = settings.load_settings()
        s["splitter_sizes"] = self.splitter.sizes()
        s["font_size"] = self.font_size
        settings.save_settings(s)

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


if __name__ == "__main__":
    main()
