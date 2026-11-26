"""Statistics screen: progress, coverage of the text, history, forecast, FSRS fitting."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
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


def progress_table(headers: list[str], rows: list[tuple[str, int, int]]) -> QTableWidget:
    """Rows of (name, known, total) with a progress bar per row."""
    table = QTableWidget(len(rows), 3)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    for r, (name, known, total) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(name))
        bar = QProgressBar()
        bar.setRange(0, max(total, 1))
        bar.setValue(known)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(8, 0, 8, 0)
        h.addWidget(bar)
        table.setCellWidget(r, 1, holder)
        pct = QTableWidgetItem(f"{100 * known / total:.1f}%  ({known}/{total})" if total else "–")
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
        retention = f"{100 * s.retention_30d:.0f}%" if s.retention_30d is not None else "–"
        for i, t in enumerate([
            tile(str(s.learned), "words learned", "Words that have graduated from learning."),
            tile(str(s.learning), "in learning", "Words met recently or forgotten, still in short steps."),
            tile(str(s.reviews_today), "reviews today", "Answers given today (the day starts at 04:00)."),
            tile(retention, "remembered (30 days)",
                 "Share of reviews of learned words in the last 30 days that you remembered."),
            tile(f"{s.streak_days} d", "study streak", "Days in a row with at least one review."),
        ]):
            tiles.addWidget(t, 0, i)
        holder = QWidget()
        holder.setLayout(tiles)
        lay.addWidget(holder)

        cov = stats.coverage(self.store)
        lay.addWidget(heading("How much of the text you know"))
        hero = QLabel(f'<span style="font-size:22pt; font-weight:600;">{100 * cov:.1f}%</span> '
                      "of all words in the Hebrew Bible belong to words you have learned.")
        hero.setWordWrap(True)
        lay.addWidget(hero)
        books = stats.coverage_by_book(self.store)
        lay.addWidget(progress_table(["Book", "Known words in the text", ""],
                                     [(b.book, b.known, b.words) for b in books]))

        lay.addWidget(heading("Decks"))
        progress = [stats.deck_progress(self.store, d) for d in decks.list_decks(self.store)]
        if progress:
            lay.addWidget(progress_table(["Deck", "Words learned", ""],
                                         [(p.name, p.learned, p.total) for p in progress]))
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
