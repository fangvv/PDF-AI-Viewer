"""生成应用 Logo（PDF + 翻译意象），保存为 .ico 文件。"""
import os
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QPen, QBrush, QIcon
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


def _build_ico(images: list, sizes: list, out_path: str) -> None:
    """手动构造多尺寸 ICO 文件（BMP 格式，Windows 标题栏/任务栏均能正确显示）。"""
    import struct
    from PIL import Image

    # 每个尺寸生成 32 位 BGRA 的 BMP 数据
    bmp_data = []
    for img in images:
        img = img.convert("RGBA")
        w, h = img.size
        # 32 位 BGRA 位图（每行 4 字节对齐）
        raw = img.tobytes("raw", "BGRA")
        row_size = w * 4
        stride = ((row_size + 3) // 4) * 4
        padded = bytearray()
        for y in range(h):
            padded += raw[y * row_size:(y + 1) * row_size]
            padded += b"\x00" * (stride - row_size)
        # BITMAPINFOHEADER (40 字节) + 像素数据
        header = struct.pack(
            "<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(padded), 0, 0, 0, 0
        )
        bmp_data.append(header + bytes(padded))

    # ICO 文件头
    count = len(sizes)
    header = struct.pack("<HHH", 0, 1, count)
    # 目录项
    entries = b""
    offset = 6 + 16 * count
    for i, size in enumerate(sizes):
        b = 0 if size >= 256 else size
        data = bmp_data[i]
        entries += struct.pack(
            "<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    with open(out_path, "wb") as f:
        f.write(header + entries + b"".join(bmp_data))


def main():
    app = QApplication(sys.argv)
    # 生成多尺寸图标
    pixmap = draw_logo(256)
    pixmap.save("logo.png", "PNG")
    # 生成多尺寸 ico（Windows 标题栏/任务栏需要小尺寸图标）
    from PIL import Image
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for size in sizes:
        pm = draw_logo(size)
        pm.save(f"_logo_{size}.png", "PNG")
        images.append(Image.open(f"_logo_{size}.png"))
    _build_ico(images, sizes, "logo.ico")
    for img in images:
        img.close()
    for size in sizes:
        os.remove(f"_logo_{size}.png")
    print("Logo 已生成：logo.png / logo.ico")


if __name__ == "__main__":
    main()
