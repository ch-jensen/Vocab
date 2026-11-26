"""Draw the app icon (an aleph on an amber tile) and write packaging/vocab.ico.

    python packaging/make_icon.py

The .ico holds PNG images at several sizes (supported since Windows Vista).
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter, QPainterPath

HERE = Path(__file__).resolve().parent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int, family: str) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.2, size * 0.2)
    p.fillPath(path, QColor("#b7791f"))
    font = QFont(family)
    font.setPixelSize(int(size * 0.78))
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, -size * 0.04, size, size), Qt.AlignCenter, "א")
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(images: list[tuple[int, bytes]], path: Path) -> None:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    path.write_bytes(header + entries + blobs)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    fid = QFontDatabase.addApplicationFont(str(HERE.parent / "fonts" / "EzraSIL.ttf"))
    family = QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else "Times New Roman"
    images = [(s, draw(s, family)) for s in SIZES]
    write_ico(images, HERE / "vocab.ico")
    (HERE / "vocab-256.png").write_bytes(images[-1][1])
    print(f"wrote {HERE / 'vocab.ico'} ({family})")
