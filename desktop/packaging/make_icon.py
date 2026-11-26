"""Draw the app icon (an aleph on an amber tile): packaging/vocab.ico and vocab.icns.

    python packaging/make_icon.py

The .ico (Windows) and .icns (macOS) hold PNG images at several sizes. The macOS
icon has a transparent margin around the tile, as macOS icons do.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter, QPainterPath

HERE = Path(__file__).resolve().parent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int, family: str, margin: float = 0.0) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    m = size * margin
    tile = size - 2 * m
    path = QPainterPath()
    path.addRoundedRect(QRectF(m, m, tile, tile), tile * 0.2, tile * 0.2)
    p.fillPath(path, QColor("#b7791f"))
    font = QFont(family)
    font.setPixelSize(max(int(tile * 0.78), 1))
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(m, m - tile * 0.04, tile, tile), Qt.AlignCenter, "א")
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


# ICNS element types holding PNG data, and their pixel sizes.
ICNS_TYPES = [(b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64), (b"ic07", 128),
              (b"ic13", 256), (b"ic08", 256), (b"ic14", 512), (b"ic09", 512), (b"ic10", 1024)]


def write_icns(family: str, path: Path) -> None:
    pngs = {size: draw(size, family, margin=0.1) for size in {s for _, s in ICNS_TYPES}}
    body = b"".join(kind + struct.pack(">I", 8 + len(pngs[size])) + pngs[size]
                    for kind, size in ICNS_TYPES)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    fid = QFontDatabase.addApplicationFont(str(HERE.parent / "fonts" / "EzraSIL.ttf"))
    family = QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else "Times New Roman"
    images = [(s, draw(s, family)) for s in SIZES]
    write_ico(images, HERE / "vocab.ico")
    (HERE / "vocab-256.png").write_bytes(images[-1][1])
    write_icns(family, HERE / "vocab.icns")
    print(f"wrote vocab.ico and vocab.icns in {HERE} ({family})")
