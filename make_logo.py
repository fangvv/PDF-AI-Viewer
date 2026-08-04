"""生成应用 Logo（PDF + 翻译意象），保存为 .ico 文件。"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QPen, QBrush
from PyQt6.QtCore import Qt, QRectF, QPointF


def draw_logo(size: int) -> QPixmap:
    """绘制 logo，返回指定尺寸的 QPixmap。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 圆角背景（蓝色渐变）
    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#4a90d9"))
    gradient.setColorAt(1.0, QColor("#2b6cb0"))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, size * 0.18, size * 0.18)

    # 白色 PDF 文档图标（左上）
    doc_w = size * 0.42
    doc_h = size * 0.52
    doc_x = size * 0.12
    doc_y = size * 0.12
    doc_rect = QRectF(doc_x, doc_y, doc_w, doc_h)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(doc_rect, size * 0.04, size * 0.04)
    # 文档上的文字线条
    painter.setPen(QPen(QColor("#4a90d9"), size * 0.035, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    line_y = doc_y + doc_h * 0.3
    for i in range(3):
        painter.drawLine(
            QPointF(doc_x + doc_w * 0.15, line_y),
            QPointF(doc_x + doc_w * (0.85 if i != 1 else 0.6), line_y)
        )
        line_y += doc_h * 0.2

    # 右侧翻译气泡（白色）
    bubble_w = size * 0.4
    bubble_h = size * 0.34
    bubble_x = size * 0.52
    bubble_y = size * 0.5
    bubble_rect = QRectF(bubble_x, bubble_y, bubble_w, bubble_h)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(bubble_rect, size * 0.05, size * 0.05)
    # 气泡小尾巴
    tail = QRectF(bubble_x + bubble_w * 0.15, bubble_y + bubble_h * 0.85,
                  bubble_w * 0.25, bubble_h * 0.2)
    painter.drawEllipse(tail)

    # 气泡里的 "文" 字（代表翻译）
    painter.setPen(QColor("#2b6cb0"))
    font = QFont("Microsoft YaHei", int(size * 0.16))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(bubble_rect, Qt.AlignmentFlag.AlignCenter, "文")

    painter.end()
    return pixmap


def main():
    app = QApplication(sys.argv)
    # 生成多尺寸图标
    pixmap = draw_logo(256)
    pixmap.save("logo.png", "PNG")
    # 保存为 ico（含多个尺寸）
    pixmap.save("logo.ico", "ICO")
    print("Logo 已生成：logo.png / logo.ico")


if __name__ == "__main__":
    main()
