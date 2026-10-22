"""Build Windows icon sizes from the original monochrome SVG mark."""
import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    assets = Path(__file__).resolve().parents[1] / "assets"
    renderer = QSvgRenderer(str(assets / "app.svg"))
    if not renderer.isValid():
        raise ValueError("The app SVG is invalid")
    entries, payloads = [], []
    sizes = (16, 24, 32, 48, 64, 128, 256)
    offset = 6 + len(sizes) * 16
    for size in sizes:
        bitmap = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        bitmap.fill(Qt.transparent)
        painter = QPainter(bitmap)
        painter.setRenderHint(QPainter.Antialiasing)
        # A light native icon plate keeps the line mark legible on dark taskbars.
        # The in-app logo uses the transparent SVG directly.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * .22, size * .22)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not bitmap.save(buffer, "PNG"):
            raise ValueError("PNG encoding failed")
        buffer.close()
        payload = bytes(data)
        edge = size if size < 256 else 0
        entries.append(struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(payload), offset))
        payloads.append(payload)
        offset += len(payload)
        if size == 256:
            bitmap.save(str(assets / "app.png"))
    (assets / "app.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries + payloads))
    print("SVG -> app.png and 7-size Windows app.ico")


if __name__ == "__main__":
    main()
