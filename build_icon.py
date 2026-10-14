"""Build a multi-resolution Windows icon from the source SVG using Qt."""
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


def main():
    app = QApplication.instance() or QApplication([])
    assets = Path(__file__).with_name("assets")
    renderer = QSvgRenderer(str(assets / "reader.svg"))
    frames = []
    sizes = (16, 24, 32, 48, 64, 128, 256)
    for size in sizes:
        canvas = QImage(size, size, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        canvas.save(buffer, "PNG")
        frames.append(bytes(buffer.data()))
    offset = 6 + 16 * len(frames)
    headers = []
    for size, frame in zip(sizes, frames):
        headers.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    (assets / "reader.ico").write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(headers) + b"".join(frames))


if __name__ == "__main__":
    main()
