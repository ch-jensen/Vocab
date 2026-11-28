"""Statistics screen: progress, coverage of the text, history, forecast, FSRS fitting."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import decks, optimize, stats
from ..decks import CORPORA
from ..session import fsrs_parameters
from ..store import Store
from .charts import BarChart


def tile(value: str, label: str, tip: str, compact: bool = False) -> QFrame:
    """A figure with its label: large and on two lines, or compact on one line."""
    box = QFrame()
    box.setObjectName("tileCompact" if compact else "tile")
    if compact:
        v = QHBoxLayout(box)
        v.setContentsMargins(10, 3, 10, 3)
        v.setSpacing(6)
    else:
        v = QVBoxLayout(box)
    big = QLabel(value)
    big.setObjectName("tileValueCompact" if compact else "tileValue")
    small = QLabel(label)
    small.setObjectName("muted")
    v.addWidget(big)
    v.addWidget(small)
    if compact:
        v.addStretch()
    box.setToolTip(tip)
    return box


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("subtitle")
    return label


CORPUS_TEXT = {"bhsa": "the Hebrew Bible", "n1904": "the Greek New Testament"}

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


def overview_tiles(store: Store, compact: bool = False, corpus: str | None = None) -> QWidget:
    """The row of overview figures (shared by the deck list and the statistics), for all
    your words or for one corpus.

    The deck list uses the compact form, so the decks themselves stay in focus."""
    s = stats.summary(store, corpus=corpus)
    tiles = QGridLayout()
    tiles.setContentsMargins(0, 0, 0, 0)
    if compact:
        tiles.setHorizontalSpacing(6)

    def pct(x):
        return f"{100 * x:.0f}%" if x is not None else "–"
    for i, t in enumerate([
        tile(str(s.mature), "mature words", MATURE_TIP, compact),
        tile(str(s.young), "young words", YOUNG_TIP, compact),
        tile(str(s.learning), "in learning", "Words met recently or forgotten, still in short steps.",
             compact),
        tile(str(s.reviews_today), "reviews today", "Answers given today (the day starts at 04:00).",
             compact),
        tile("–" if s.retention_30d is None else f"{pct(s.retention_young)} · {pct(s.retention_mature)}",
             "remembered: young · mature",
             "Share of reviews in the last 30 days that you remembered, for young and for "
             f"mature words (a review counts as mature if the word had gone {stats.MATURE_DAYS} "
             f"days or more since its previous review). All together: {pct(s.retention_30d)}.",
             compact),
        tile(f"{s.streak_days} d", "study streak", "Days in a row with at least one review.", compact),
    ]):
        tiles.addWidget(t, 0, i)
    holder = QWidget()
    holder.setObjectName("overview")
    holder.setLayout(tiles)
    return holder


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


def corpora_in_database(store: Store) -> list[str]:
    return [c for c in CORPORA if store.books(c)]


class CorpusCard(QFrame):
    """A brief overview of one text, with a button to its detailed statistics."""

    def __init__(self, store: Store, corpus: str, on_details, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.corpus = corpus
        cov = stats.coverage_detail(store, corpus)
        s = stats.summary(store, corpus=corpus)
        n_decks = sum(1 for d in decks.list_decks(store) if d.config.corpus == corpus)
        reviews_30 = sum(n for _, n in stats.reviews_per_day(store, 30, corpus=corpus))

        title = QLabel(CORPORA[corpus])
        title.setObjectName("subtitle")
        self.details = QPushButton("Details ›")
        self.details.setToolTip(f"Detailed statistics for {CORPUS_TEXT[corpus]}")
        self.details.clicked.connect(lambda: on_details(corpus))
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.details)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.addLayout(top)
        if s.learned + s.learning == 0:
            note = QLabel("Not started yet. Make a deck with this text to begin.")
            note.setObjectName("muted")
            v.addWidget(note)
            return
        self.share = QLabel(
            f'<span style="font-size:18pt; font-weight:600;">{100 * cov.share:.1f}%</span>'
            f' of the text learned <span style="color:#718096;">· {100 * cov.mature_share:.1f}% mature</span>')
        v.addWidget(self.share)
        v.addWidget(StackedBar(cov.mature, cov.known - cov.mature, cov.words))
        decks_text = "1 deck" if n_decks == 1 else f"{n_decks} decks"
        words = "1 word" if s.learned == 1 else f"{s.learned} words"
        figures = QLabel(f"{words} learned ({s.mature} mature) · {s.learning} in learning · "
                         f"{decks_text} · {reviews_30} reviews in the last 30 days")
        figures.setObjectName("muted")
        figures.setWordWrap(True)
        v.addWidget(figures)


def page_header(title_text: str, back_text: str, on_back) -> tuple[QHBoxLayout, QLabel]:
    back = QPushButton(back_text)
    back.setFlat(True)
    back.clicked.connect(on_back)
    title = QLabel(title_text)
    title.setObjectName("title")
    header = QHBoxLayout()
    header.addWidget(back)
    header.addWidget(title)
    header.addStretch()
    return header, title


class ScrollPage(QWidget):
    """A page with a fixed header and a scrolling body that is rebuilt by refresh()."""

    def __init__(self, title_text: str, back_text: str, parent=None):
        super().__init__(parent)
        header, self.title = page_header(title_text, back_text, self._back)
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

    def _back(self) -> None:
        self.finished.emit()

    def clear(self) -> QVBoxLayout:
        while self.body_layout.count():
            widget = self.body_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)          # gone at once, not only when Qt next idles
                widget.deleteLater()
        return self.body_layout


def charts(lay: QVBoxLayout, store: Store, corpus: str | None = None) -> None:
    lay.addWidget(heading("Reviews in the last 30 days"))
    history = BarChart("reviews")
    history.set_data(stats.reviews_per_day(store, 30, corpus=corpus))
    lay.addWidget(history)
    lay.addWidget(heading("Words due in the next 30 days"))
    fc = BarChart("words due")
    fc.set_data(stats.forecast(store, 30, corpus=corpus))
    lay.addWidget(fc)


class StatsPage(ScrollPage):
    """Overview: your figures, a card per text, and your reviews over the last and next 30 days."""

    finished = Signal()
    details_requested = Signal(str)     # corpus

    def __init__(self, store: Store, parent=None):
        super().__init__("Statistics", "← Decks", parent)
        self.store = store
        self.cards: list[CorpusCard] = []

    def refresh(self) -> None:
        lay = self.clear()
        lay.addWidget(overview_tiles(self.store))

        lay.addWidget(heading("Your texts"))
        self.cards = [CorpusCard(self.store, c, self.details_requested.emit)
                      for c in corpora_in_database(self.store)]
        for card in self.cards:
            lay.addWidget(card)

        charts(lay, self.store)

        lay.addWidget(heading("Personal scheduling"))
        self.scheduling = SchedulingSection(self.store)
        lay.addWidget(self.scheduling)
        lay.addStretch()


class CorpusStatsPage(ScrollPage):
    """Detailed statistics for one text: figures, coverage per book, decks, 30-day charts."""

    finished = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__("", "← Statistics", parent)
        self.store = store
        self.corpus = "bhsa"

    def show_corpus(self, corpus: str) -> None:
        self.corpus = corpus
        self.title.setText(CORPORA[corpus])
        self.refresh()

    def refresh(self) -> None:
        lay = self.clear()
        corpus, text = self.corpus, CORPUS_TEXT[self.corpus]
        lay.addWidget(overview_tiles(self.store, corpus=corpus))

        cov = stats.coverage_detail(self.store, corpus)
        lay.addWidget(heading(f"How much of {text} you know"))
        hero = QLabel(f'<span style="font-size:22pt; font-weight:600;">{100 * cov.share:.1f}%</span> '
                      f"of all words in {text} belong to words you have learned; "
                      f'<span style="font-size:22pt; font-weight:600;">{100 * cov.mature_share:.1f}%</span> '
                      "to mature words.")
        hero.setWordWrap(True)
        lay.addWidget(hero)
        lay.addWidget(legend())
        books = stats.coverage_by_book(self.store, corpus=corpus)
        lay.addWidget(progress_table(["Book", "Known words in the text", ""],
                                     [(b.book, b.mature, b.known - b.mature, b.words)
                                      for b in books], unit="%"))

        lay.addWidget(heading("Decks"))
        progress = [stats.deck_progress(self.store, d) for d in decks.list_decks(self.store)
                    if d.config.corpus == corpus]
        if progress:
            lay.addWidget(progress_table(["Deck", "Words learned", ""],
                                         [(p.name, p.mature, p.young, p.total) for p in progress]))
        else:
            none = QLabel("No decks with this text yet.")
            none.setObjectName("muted")
            lay.addWidget(none)

        charts(lay, self.store, corpus)
        lay.addStretch()


class SchedulingSection(QWidget):
    """Fitting FSRS to the user's own answers (or going back to the defaults),
    shown at the bottom of the statistics overview."""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._thread: QThread | None = None
        explain = QLabel(
            "FSRS can be fitted to your own answers, so that intervals match how quickly "
            f"<i>you</i> forget. This needs at least {optimize.MIN_REVIEWS} reviews; the "
            "fitted parameters are only used if they predict your answers better.")
        explain.setWordWrap(True)
        explain.setObjectName("muted")
        self.fit_status = QLabel(optimize.status(store))
        self.fit_status.setWordWrap(True)
        self.fit_btn = QPushButton("Fit to my answers")
        n = optimize.total_reviews(store)
        self.fit_btn.setEnabled(n >= optimize.MIN_REVIEWS)
        if n < optimize.MIN_REVIEWS:
            self.fit_btn.setToolTip(f"{n} of {optimize.MIN_REVIEWS} reviews so far.")
        self.fit_btn.clicked.connect(self.fit)
        self.reset_btn = QPushButton("Use default parameters")
        self.reset_btn.setEnabled(fsrs_parameters(store) is not None)
        self.reset_btn.clicked.connect(self.reset_parameters)
        row = QHBoxLayout()
        row.addWidget(self.fit_btn)
        row.addWidget(self.reset_btn)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(explain)
        layout.addWidget(self.fit_status)
        layout.addLayout(row)

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
        self.fit_status.setText(optimize.status(self.store))
        self.reset_btn.setEnabled(fsrs_parameters(self.store) is not None)

    def reset_parameters(self) -> None:
        optimize.reset(self.store)
        self.fit_status.setText(optimize.status(self.store))
        self.reset_btn.setEnabled(False)
