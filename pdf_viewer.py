"""PDF 阅读面板。

使用 PyMuPDF (fitz) 渲染页面，支持：
- 鼠标刷选文本（拖拽选择）
- 滚轮翻页 / 滚动
- 缩放
- 页码跳转

性能优化：按需渲染，只渲染当前可见的页面，避免打开大 PDF 时卡顿。
"""

import fitz  # PyMuPDF
import re

from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QScrollArea, QVBoxLayout, QLabel


def clean_text(text: str) -> str:
    """清洗 PDF 提取的文本，恢复句子连续性。

    - 处理连字符断词（如 "cogeneration-\\nbased" → "cogeneration-based"）
    - 其余换行替换为空格（英文句子跨行）
    - 合并多余空格
    """
    if not text:
        return ""
    # 连字符断词：单词末尾的 "-" + 换行 → 直接连接
    text = re.sub(r"-\s*\n\s*", "-", text)
    # 其余换行替换为空格
    text = re.sub(r"\s*\n\s*", " ", text)
    # 合并多余空格
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class PdfPageWidget(QWidget):
    """单个 PDF 页面，支持文本刷选，延迟渲染。"""

    textSelected = pyqtSignal(str)
    textSelectedAt = pyqtSignal(str, object)  # 文本, 全局坐标 QPoint
    linkClicked = pyqtSignal(str)

    def __init__(self, page: fitz.Page, zoom: float, parent=None):
        super().__init__(parent)
        self.page = page
        self.zoom = zoom
        self.pixmap = None
        self._rendered = False
        # 先按缩放后的尺寸占位，保证布局正确
        rect = page.rect
        self.setFixedSize(int(rect.width * zoom), int(rect.height * zoom))
        self.setMouseTracking(True)
        # 文本选择光标（I 型）
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._sel_start = None
        self._sel_end = None
        self._sel_rects = []
        # 页面链接（uri 链接）
        self._links = []
        for link in page.get_links():
            if link.get("uri"):
                self._links.append((fitz.Rect(link["from"]), link["uri"]))
        self._hover_link = None

    def _link_at(self, pos) -> str | None:
        """返回位置 pos 处的链接 URI，无则返回 None。"""
        pdf_x = pos.x() / self.zoom
        pdf_y = pos.y() / self.zoom
        point = fitz.Point(pdf_x, pdf_y)
        for rect, uri in self._links:
            if rect.contains(point):
                return uri
        return None

    def ensure_rendered(self):
        """确保页面已渲染（首次可见时调用）。"""
        if self._rendered:
            return
        self._render()
        self.update()

    def _render(self):
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = self.page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        self.pixmap = QPixmap.fromImage(img.copy())
        self._rendered = True
        self.setFixedSize(self.pixmap.size())

    def set_zoom(self, zoom: float):
        self.zoom = zoom
        self._rendered = False
        self.pixmap = None
        self._sel_rects = []
        rect = self.page.rect
        self.setFixedSize(int(rect.width * zoom), int(rect.height * zoom))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.pixmap:
            painter.drawPixmap(0, 0, self.pixmap)
        else:
            # 未渲染时画浅色占位背景
            painter.fillRect(self.rect(), QColor(245, 245, 245))
        # 绘制选中高亮
        if self._sel_rects:
            painter.setPen(QPen(QColor(0, 120, 215, 0)))
            painter.setBrush(QColor(0, 120, 215, 80))
            for rect in self._sel_rects:
                painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._sel_start = event.position()
            self._sel_end = self._sel_start
            self._sel_rects = []
            self.update()

    def mouseMoveEvent(self, event):
        # 悬停检测：在链接上显示手型光标
        if self._sel_start is None:
            uri = self._link_at(event.position())
            if uri and not self._hover_link:
                self._hover_link = uri
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif not uri and self._hover_link:
                self._hover_link = None
                self.setCursor(Qt.CursorShape.IBeamCursor)
        if self._sel_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._sel_end = event.position()
            self._update_selection()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._sel_start is not None:
            self._sel_end = event.position()
            self._update_selection()
            text = self._extract_selected_text()
            # 判断是否为点击（未拖动）且点在链接上
            if self._sel_start == self._sel_end:
                uri = self._link_at(event.position())
                if uri:
                    self.linkClicked.emit(uri)
            elif text:
                self.textSelected.emit(text)
                # 同时发出全局坐标，用于显示浮动翻译按钮
                self.textSelectedAt.emit(text, event.globalPosition().toPoint())
            self._sel_start = None
            self._sel_end = None

    def _get_selected_spans(self):
        """返回与刷选区域相交的文本 span 列表（按阅读顺序）。

        每个 span: (text, x0, y0, x1, y1)
        """
        if self._sel_start is None or self._sel_end is None:
            return []
        rect = QRectF(self._sel_start, self._sel_end).normalized()
        clip = fitz.Rect(
            rect.left() / self.zoom,
            rect.top() / self.zoom,
            rect.right() / self.zoom,
            rect.bottom() / self.zoom,
        )
        # 获取页面结构化文本
        data = self.page.get_text("dict")
        selected = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # 只处理文本块
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox")
                    if not bbox:
                        continue
                    span_rect = fitz.Rect(bbox)
                    # 判断 span 是否与刷选区域相交
                    if span_rect.intersects(clip):
                        selected.append((span.get("text", ""), *bbox))
        return selected

    def _update_selection(self):
        spans = self._get_selected_spans()
        self._sel_rects = []
        for text, x0, y0, x1, y1 in spans:
            r = QRectF(
                x0 * self.zoom,
                y0 * self.zoom,
                (x1 - x0) * self.zoom,
                (y1 - y0) * self.zoom,
            )
            self._sel_rects.append(r)

    def _extract_selected_text(self) -> str:
        spans = self._get_selected_spans()
        if not spans:
            return ""
        # 按 span 顺序拼接文本，并根据几何位置判断分隔符：
        # - 相邻 span 换行（y 坐标不同）→ 插入换行，交给 clean_text 转成空格
        # - 同一行但 x 方向有间隙 → 插入空格，避免 "for"+"edge" 粘连成 "foredge"
        # - 否则直接拼接（同一单词被拆成多个 span 的情况）
        parts = []
        prev = None
        for text, x0, y0, x1, y1 in spans:
            if not text:
                continue
            if prev is not None:
                _, px0, py0, px1, py1 = prev
                # 换行判断：y 中心相差超过半行高
                cur_cy = (y0 + y1) / 2
                prev_cy = (py0 + py1) / 2
                line_h = max(y1 - y0, py1 - py0, 1e-6)
                if abs(cur_cy - prev_cy) > line_h * 0.5:
                    parts.append("\n")
                elif x0 > px1 + 1e-6:  # 同一行但 x 有间隙
                    parts.append(" ")
            parts.append(text)
            prev = (text, x0, y0, x1, y1)
        raw = "".join(parts)
        return clean_text(raw)


class PdfViewer(QScrollArea):
    """PDF 阅读器（滚动区域，按需渲染页面）。"""

    pageChanged = pyqtSignal(int, int)  # 当前页, 总页数
    textSelected = pyqtSignal(str)
    textSelectedAt = pyqtSignal(str, object)  # 文本, 全局坐标 QPoint
    linkClicked = pyqtSignal(str)
    zoomChanged = pyqtSignal(float)  # 缩放比例变化（Ctrl+滚轮）

    # 缩放模式
    FIT_NONE = 0      # 固定百分比
    FIT_WIDTH = 1     # 适合宽度
    FIT_PAGE = 2      # 适合页面

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.zoom = 1.5
        self.fit_mode = self.FIT_NONE
        self.page_widgets = []
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._container)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # 空状态提示（未打开 PDF 时显示）
        self._empty_label = QLabel("打开一个 PDF 文件开始阅读")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "color: #999999; font-size: 16px; background: transparent;"
        )
        self._layout.addWidget(self._empty_label)
        # 防抖定时器：滚动停止后渲染可见页
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._render_visible)
        # 防抖定时器：窗口大小变化后重新适配
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(100)
        self._fit_timer.timeout.connect(self._apply_fit)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 适合宽度/页面模式下，窗口大小变化时自动重新适配（防抖）
        if self.fit_mode != self.FIT_NONE and self.page_widgets:
            self._fit_timer.start()

    def wheelEvent(self, event):
        # Ctrl + 滚轮：缩放（前推放大，后推缩小）
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            step = 10
            new_pct = int(round(self.zoom * 100)) + (step if delta > 0 else -step)
            new_pct = max(25, min(new_pct, 400))
            self.set_zoom(new_pct / 100.0)
            self.zoomChanged.emit(self.zoom)
            event.accept()
            return
        super().wheelEvent(event)

    def load_document(self, path: str):
        self.doc = fitz.open(path)
        self._clear_pages()
        self._empty_label.hide()
        # 重新启用滚动条
        self.verticalScrollBar().setEnabled(True)
        self.horizontalScrollBar().setEnabled(True)
        # 只创建占位 widget，不渲染位图
        for page in self.doc:
            w = PdfPageWidget(page, self.zoom)
            w.textSelected.connect(self.textSelected)
            w.textSelectedAt.connect(self.textSelectedAt)
            w.linkClicked.connect(self.linkClicked)
            self._layout.addWidget(w)
            self.page_widgets.append(w)
        self.pageChanged.emit(1, len(self.page_widgets))
        # 渲染首屏
        QTimer.singleShot(0, self._render_visible)

    def load_document_progress(self, path: str, progress_callback=None) -> int:
        """带进度回调的加载，返回总页数。

        progress_callback(done, total) 在每页创建后调用。
        """
        self.doc = fitz.open(path)
        self._clear_pages()
        self._empty_label.hide()
        # 重新启用滚动条
        self.verticalScrollBar().setEnabled(True)
        self.horizontalScrollBar().setEnabled(True)
        total = self.doc.page_count
        for i, page in enumerate(self.doc):
            w = PdfPageWidget(page, self.zoom)
            w.textSelected.connect(self.textSelected)
            w.textSelectedAt.connect(self.textSelectedAt)
            w.linkClicked.connect(self.linkClicked)
            self._layout.addWidget(w)
            self.page_widgets.append(w)
            if progress_callback:
                progress_callback(i + 1, total)
        self.pageChanged.emit(1, total)
        # 渲染首屏
        QTimer.singleShot(0, self._render_visible)
        return total

    def _clear_pages(self):
        for w in self.page_widgets:
            w.deleteLater()
        self.page_widgets = []

    def clear_document(self):
        """清空当前文档。"""
        self._clear_pages()
        if self.doc:
            self.doc.close()
            self.doc = None
        # 重置并禁用滚动条，避免关闭后仍可拖动
        self.verticalScrollBar().setValue(0)
        self.verticalScrollBar().setEnabled(False)
        self.horizontalScrollBar().setValue(0)
        self.horizontalScrollBar().setEnabled(False)
        # 显示空状态提示
        self._empty_label.show()
        self.pageChanged.emit(1, 1)

    def _capture_position(self):
        """记录当前页及其在页内的相对位置（0~1），用于缩放后恢复。"""
        if not self.page_widgets:
            return None
        value = self.verticalScrollBar().value()
        for i, w in enumerate(self.page_widgets):
            if w.y() <= value < w.y() + w.height():
                ratio = (value - w.y()) / w.height() if w.height() else 0.0
                return i, ratio
        return None

    def _restore_position(self, pos):
        """根据记录的 (页索引, 页内相对位置) 恢复滚动位置。"""
        if pos is None or not self.page_widgets:
            return
        i, ratio = pos
        if i < 0 or i >= len(self.page_widgets):
            return
        w = self.page_widgets[i]
        self.verticalScrollBar().setValue(int(w.y() + ratio * w.height()))

    def set_zoom(self, zoom: float):
        """设置固定百分比缩放。"""
        self.fit_mode = self.FIT_NONE
        self.zoom = zoom
        pos = self._capture_position()
        for w in self.page_widgets:
            w.set_zoom(zoom)
        # 强制布局更新，确保 w.y() 正确
        self._container.adjustSize()
        self._layout.activate()
        # 恢复缩放前的阅读位置
        self._restore_position(pos)
        # 延迟到布局更新后再渲染
        QTimer.singleShot(0, self._render_visible)

    def fit_width(self):
        """适合宽度：按视口宽度缩放。"""
        self.fit_mode = self.FIT_WIDTH
        self._apply_fit()

    def fit_page(self):
        """适合页面：整页显示在视口内。"""
        self.fit_mode = self.FIT_PAGE
        self._apply_fit()

    def _apply_fit(self):
        if not self.page_widgets:
            return
        # 计算视口可用尺寸（减去滚动条宽度）
        vw = self.viewport().width()
        vh = self.viewport().height()
        if vw <= 0 or vh <= 0:
            return
        # 取第一页尺寸作为基准
        page_rect = self.page_widgets[0].page.rect
        pw, ph = page_rect.width, page_rect.height
        if self.fit_mode == self.FIT_WIDTH:
            zoom = (vw - 20) / pw
        else:  # FIT_PAGE
            zoom = min((vw - 20) / pw, (vh - 20) / ph)
        zoom = max(0.1, min(zoom, 5.0))
        self.zoom = zoom
        pos = self._capture_position()
        for w in self.page_widgets:
            w.set_zoom(zoom)
        # 强制布局更新，确保 w.y() 正确
        self._container.adjustSize()
        self._layout.activate()
        # 恢复缩放前的阅读位置
        self._restore_position(pos)
        # 延迟到布局更新后再渲染
        QTimer.singleShot(0, self._render_visible)

    def _on_scroll(self, value):
        if not self.page_widgets:
            return
        # 计算当前可见页
        view_top = value
        view_bottom = value + self.viewport().height()
        for i, w in enumerate(self.page_widgets):
            w_top = w.y()
            w_bottom = w.y() + w.height()
            if w_top <= view_top < w_bottom or w_top <= view_bottom <= w_bottom:
                self.pageChanged.emit(i + 1, len(self.page_widgets))
                break
        # 防抖：滚动停止后渲染
        self._render_timer.start()

    def _render_visible(self):
        """渲染当前可见的页面（含上下各一页缓冲）。"""
        if not self.page_widgets:
            return
        value = self.verticalScrollBar().value()
        view_top = value
        view_bottom = value + self.viewport().height()
        rendered_any = False
        for i, w in enumerate(self.page_widgets):
            w_top = w.y()
            w_bottom = w.y() + w.height()
            # 可见或接近可见（上下各一页缓冲）
            if w_bottom >= view_top - w.height() and w_top <= view_bottom + w.height():
                w.ensure_rendered()
                rendered_any = True
        # 兜底：如果布局未更新导致没有页面被判定为可见，强制渲染滚动位置附近的页面
        if not rendered_any:
            for i, w in enumerate(self.page_widgets):
                if w.y() + w.height() >= view_top:
                    w.ensure_rendered()
                    break

    def go_to_page(self, page: int):
        """跳转到指定页（1-based）。"""
        if not self.page_widgets:
            return
        page = max(1, min(page, len(self.page_widgets)))
        w = self.page_widgets[page - 1]
        self.verticalScrollBar().setValue(w.y())
        self.pageChanged.emit(page, len(self.page_widgets))
        self._render_visible()

    def current_page(self) -> int:
        if not self.page_widgets:
            return 1
        value = self.verticalScrollBar().value()
        for i, w in enumerate(self.page_widgets):
            if w.y() <= value < w.y() + w.height():
                return i + 1
        return 1

    def current_page_text(self) -> str:
        """返回当前页的文本内容。"""
        if not self.page_widgets:
            return ""
        page = self.current_page()
        w = self.page_widgets[page - 1]
        return clean_text(w.page.get_text("text"))

    def scroll_to(self, offset: int):
        self.verticalScrollBar().setValue(offset)
