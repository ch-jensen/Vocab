"""A small single-series column chart drawn with QPainter (no plotting library).

Follows the chart rules used throughout the app: one hue, columns at most
24 px wide with a 4 px rounded top and square base on one baseline, a 2 px gap
between columns, faint axis, a few labels only, and the exact value on hover.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

SERIES = QColor("#2a78d6")
SERIES_HOVER = QColor("#1f5fae")
AXIS = QColor("#d5d4cf")
TEXT_MUTED = QColor("#52514e")

MAX_BAR = 24
GAP = 2
RADIUS = 4


def nice_max(value: int) -> int:
    """Round the top of the scale up to 1, 2 or 5 x 10^n."""
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


class BarChart(QWidget):
    def __init__(self, unit: str, parent=None):
        super().__init__(parent)
        self.unit = unit                       # e.g. "reviews"
        self.data: list[tuple[date, int]] = []
        self.hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[tuple[date, int]]) -> None:
        self.data = data
        self.hover = None
        self.update()

    # geometry ---------------------------------------------------------------
    def _plot(self) -> QRectF:
        return QRectF(36, 8, max(self.width() - 44, 10), max(self.height() - 34, 10))

    def _slot(self, i: int) -> tuple[float, float]:
        plot = self._plot()
        slot = plot.width() / max(len(self.data), 1)
        width = max(min(slot - GAP, MAX_BAR), 1)
        x = plot.left() + i * slot + (slot - width) / 2
        return x, width

    def _index_at(self, x: float) -> int | None:
        plot = self._plot()
        if not self.data or not plot.left() <= x <= plot.right():
            return None
        i = int((x - plot.left()) / (plot.width() / len(self.data)))
        return min(i, len(self.data) - 1)

    # painting ---------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot()
        top = nice_max(max((n for _, n in self.data), default=0))

        p.setPen(QPen(AXIS, 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        p.setPen(TEXT_MUTED)
        font = p.font()
        font.setPointSizeF(font.pointSizeF() * 0.85)
        p.setFont(font)
        p.drawText(QRectF(0, plot.top() - 6, 30, 14), Qt.AlignRight | Qt.AlignVCenter, str(top))
        p.drawText(QRectF(0, plot.bottom() - 7, 30, 14), Qt.AlignRight | Qt.AlignVCenter, "0")

        for i, (_, n) in enumerate(self.data):
            if n <= 0:
                continue
            x, w = self._slot(i)
            h = max(plot.height() * n / top, 2)
            y = plot.bottom() - h
            r = min(RADIUS, w / 2, h)
            path = QPainterPath()
            path.moveTo(x, plot.bottom())
            path.lineTo(x, y + r)
            path.quadTo(x, y, x + r, y)
            path.lineTo(x + w - r, y)
            path.quadTo(x + w, y, x + w, y + r)
            path.lineTo(x + w, plot.bottom())
            path.closeSubpath()
            p.fillPath(path, SERIES_HOVER if i == self.hover else SERIES)

        # A few date labels: first, middle, last.
        if self.data:
            for i in sorted({0, len(self.data) // 2, len(self.data) - 1}):
                x, w = self._slot(i)
                p.drawText(QRectF(x + w / 2 - 40, plot.bottom() + 4, 80, 16), Qt.AlignHCenter,
                           self._label(self.data[i][0]))
        p.end()

    @staticmethod
    def _label(d: date) -> str:
        return f"{d.day} {d.strftime('%b')}"

    # hover ------------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        i = self._index_at(event.position().x())
        if i != self.hover:
            self.hover = i
            self.update()
        if i is None:
            QToolTip.hideText()
            return
        d, n = self.data[i]
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"{d.strftime('%a')} {self._label(d)}: {n} {self.unit}", self)

    def leaveEvent(self, _event) -> None:
        self.hover = None
        self.update()
        QToolTip.hideText()
