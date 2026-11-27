"""Statistics screen: progress, coverage of the text, history, forecast, FSRS fitting."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import decks, optimize, stats
from ..session import fsrs_parameters
from ..store import Store
from .charts import BarChart


def tile(value: str, label: str, tip: str) -> QFrame:
    box = QFrame()
    box.setObjectName("tile")
    v = QVBoxLayout(box)
    big = QLabel(value)
    big.setObjectName("tileValue")
    small = QLabel(label)
    small.setObjectName("muted")
    v.addWidget(big)
    v.addWidget(small)
    box.setToolTip(tip)
    return box


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("subtitle")
    return label


MATURE_COLOUR = QColor("#2a78d6")
YOUNG_COLOUR = QColor("#8fbbee")
TRACK_COLOUR = QColor("#e8e7e2")

MATURE_TIP = (f"<b>Mature</b>: learned words with an interval of {stats.MATURE_DAYS} days or more. "
              "You have recalled them several times with growing gaps: your solid vocabulary.")
YOUNG_TIP = (f"<b>Young</b>: learned words with an interval under {stats.MATURE_DAYS} days. "
             "You know them, but the memory is still being consolidated.")


class StackedBar(QWidget):
    """One bar: mature (dark), young (light) and the rest (track), 2 px apart."""

    def __init__(self, mature: int, young: int, total: int, parent=None):
        super().__init__(parent)
        self.mature, self.young, self.total = mature, young, max(total, 1)
        self.setFixedHeight(10)
        self.setMinimumWidth(80)
        self.setToolTip(f"Mature {mature} · young {young} · of {total}")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        p.setBrush(TRACK_COLOUR)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        x = 0.0
        for value, colour in ((self.mature, MATURE_COLOUR), (self.young, YOUNG_COLOUR)):
            if value <= 0:
                continue
            seg = max(w * value / self.total, 2)
            p.setBrush(colour)
            p.drawRoundedRect(QRectF(x, 0, min(seg, w - x), h), h / 2, h / 2)
            x += seg + 2                        # 2 px gap between the segments
        p.end()


def legend() -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    for colour, label, tip in ((MATURE_COLOUR, f"Mature ({stats.MATURE_DAYS}+ days)", MATURE_TIP),
                               (YOUNG_COLOUR, "Young", YOUNG_TIP)):
        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background: {colour.name()}; border-radius: 3px;")
        text = QLabel(label)
        for part in (swatch, text):
            part.setToolTip(tip)
        row.addWidget(swatch)
        row.addWidget(text)
        row.addSpacing(12)
    row.addStretch()
    return w


def progress_table(headers: list[str], rows: list[tuple[str, int, int, int]],
                   unit: str = "") -> QTableWidget:
    """Rows of (name, mature, young, total) with a two-part bar per row."""
    table = QTableWidget(len(rows), 3)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    for r, (name, mature, young, total) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(name))
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(8, 0, 8, 0)
        h.addWidget(StackedBar(mature, young, total))
        table.setCellWidget(r, 1, holder)
        known = mature + young
        if total:
            text = (f"{100 * known / total:.1f}% (mature {100 * mature / total:.1f}%)" if unit == "%"
                    else f"{known} of {total} ({mature} mature)")
        else:
            text = "–"
        pct = QTableWidgetItem(text)
        pct.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(r, 2, pct)
    table.setFixedHeight(min(table.verticalHeader().length() + table.horizontalHeader().height() + 4,
                             420))
    return table


class FitWorker(QObject):
    done = Signal(object)

    def __init__(self, data, current):
        super().__init__()
        self.data, self.current = data, current

    def run(self) -> None:
        try:
            self.done.emit(optimize.fit(self.data, self.current))
        except Exception as exc:     # report rather than crash the app
            self.done.emit(exc)


class StatsPage(QWidget):
    finished = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._thread: QThread | None = None

        back = QPushButton("← Decks")
        back.setFlat(True)
        back.clicked.connect(self.finished.emit)
        title = QLabel("Statistics")
        title.setObjectName("title")
        header = QHBoxLayout()
        header.addWidget(back)
        header.addWidget(title)
        header.addStretch()

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 8, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lay = self.body_layout
        s = stats.summary(self.store)

        tiles = QGridLayout()

        def pct(x):
            return f"{100 * x:.0f}%" if x is not None else "–"
        for i, t in enumerate([
            tile(str(s.mature), "mature words", MATURE_TIP),
            tile(str(s.young), "young words", YOUNG_TIP),
            tile(str(s.learning), "in learning", "Words met recently or forgotten, still in short steps."),
            tile(str(s.reviews_today), "reviews today", "Answers given today (the day starts at 04:00)."),
            tile("–" if s.retention_30d is None else f"{pct(s.retention_young)} · {pct(s.retention_mature)}",
                 "remembered: young · mature",
                 "Share of reviews in the last 30 days that you remembered, for young and for "
                 f"mature words (a review counts as mature if the word had gone {stats.MATURE_DAYS} "
                 f"days or more since its previous review). All together: {pct(s.retention_30d)}."),
            tile(f"{s.streak_days} d", "study streak", "Days in a row with at least one review."),
        ]):
            tiles.addWidget(t, 0, i)
        holder = QWidget()
        holder.setLayout(tiles)
        lay.addWidget(holder)

        cov = stats.coverage_detail(self.store)
        lay.addWidget(heading("How much of the text you know"))
        hero = QLabel(f'<span style="font-size:22pt; font-weight:600;">{100 * cov.share:.1f}%</span> '
                      "of all words in the Hebrew Bible belong to words you have learned; "
                      f'<span style="font-size:22pt; font-weight:600;">{100 * cov.mature_share:.1f}%</span> '
                      "to mature words.")
        hero.setWordWrap(True)
        lay.addWidget(hero)
        lay.addWidget(legend())
        books = stats.coverage_by_book(self.store)
        lay.addWidget(progress_table(["Book", "Known words in the text", ""],
                                     [(b.book, b.mature, b.known - b.mature, b.words)
                                      for b in books], unit="%"))

        lay.addWidget(heading("Decks"))
        progress = [stats.deck_progress(self.store, d) for d in decks.list_decks(self.store)]
        if progress:
            lay.addWidget(progress_table(["Deck", "Words learned", ""],
                                         [(p.name, p.mature, p.young, p.total) for p in progress]))
        else:
            lay.addWidget(QLabel("No decks yet."))

        lay.addWidget(heading("Reviews in the last 30 days"))
        history = BarChart("reviews")
        history.set_data(stats.reviews_per_day(self.store, 30))
        lay.addWidget(history)

        lay.addWidget(heading("Words due in the next 30 days"))
        fc = BarChart("words due")
        fc.set_data(stats.forecast(self.store, 30))
        lay.addWidget(fc)

        lay.addWidget(heading("Personal scheduling"))
        explain = QLabel(
            "FSRS can be fitted to your own answers, so that intervals match how quickly "
            f"<i>you</i> forget. This needs at least {optimize.MIN_REVIEWS} reviews; the "
            "fitted parameters are only used if they predict your answers better.")
        explain.setWordWrap(True)
        explain.setObjectName("muted")
        lay.addWidget(explain)
        self.fit_status = QLabel(optimize.status(self.store))
        lay.addWidget(self.fit_status)
        buttons = QHBoxLayout()
        self.fit_btn = QPushButton("Fit to my answers")
        n = optimize.total_reviews(self.store)
        self.fit_btn.setEnabled(n >= optimize.MIN_REVIEWS)
        if n < optimize.MIN_REVIEWS:
            self.fit_btn.setToolTip(f"{n} of {optimize.MIN_REVIEWS} reviews so far.")
        self.fit_btn.clicked.connect(self.fit)
        reset = QPushButton("Use default parameters")
        reset.setEnabled(fsrs_parameters(self.store) is not None)
        reset.clicked.connect(self.reset_parameters)
        buttons.addWidget(self.fit_btn)
        buttons.addWidget(reset)
        buttons.addStretch()
        row = QWidget()
        row.setLayout(buttons)
        lay.addWidget(row)
        lay.addStretch()

    # --- FSRS fitting ------------------------------------------------------------
    def fit(self) -> None:
        data = optimize.training_data(self.store)
        self.fit_btn.setEnabled(False)
        self.fit_status.setText("Fitting… this can take a little while.")
        self._thread = QThread(self)
        self._worker = FitWorker(data, fsrs_parameters(self.store))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._fitted)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _fitted(self, result) -> None:
        if isinstance(result, Exception):
            QMessageBox.warning(self, "Fitting failed", str(result))
        else:
            optimize.apply(self.store, result)
            QMessageBox.information(self, "Personal scheduling", result.message)
        self.refresh()

    def reset_parameters(self) -> None:
        optimize.reset(self.store)
        self.refresh()
