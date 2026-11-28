"""Home screen: the list of decks with today's counts."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import deckfile, decks, stats
from ..session import StudySession
from ..store import Store
from .common import BAD, GOOD, MUTED
from .counts import DUE_TIP, LEARNING_TIP, NEW_TIP, learning_text
from .deck_editor import DeckEditor
from .stats_page import StackedBar, overview_tiles

# A soft colour per language for the deck's language label: (background, text).
LANGUAGE_COLOURS = {"Hebrew": ("#fbefd9", "#7a4e0c"), "Aramaic": ("#efe8f8", "#563a86"),
                    "Greek": ("#e3eefb", "#1d5aa6")}


def language_pill(text: str) -> QLabel:
    first = text.split(" and ")[0]
    bg, fg = LANGUAGE_COLOURS.get(first, ("#edf2f7", "#4a5568"))
    pill = QLabel(text)
    pill.setObjectName("pill")
    pill.setStyleSheet(f"QLabel#pill {{ background: {bg}; color: {fg}; border-radius: 9px; "
                       "padding: 1px 9px; font-size: 9.5pt; }}")
    pill.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return pill


class DeckCard(QFrame):
    """One deck: name, language, progress, today's counts and a Study button."""

    clicked = Signal(object)          # DeckCard
    study = Signal(object)            # Deck

    def __init__(self, store: Store, deck: decks.Deck, parent=None):
        super().__init__(parent)
        self.deck = deck
        self.setObjectName("deckCard")
        self.setCursor(Qt.PointingHandCursor)
        self.counts = StudySession(store, deck).counts()
        progress = stats.deck_progress(store, deck)
        self.language = decks.language_label(store.con, deck.config)

        self.name = QLabel(deck.name)
        self.name.setObjectName("deckName")
        pill = language_pill(self.language)
        pill.setToolTip(decks.CORPORA[deck.config.corpus])
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.name)
        top.addWidget(pill)
        top.addStretch()

        self.details = QLabel(f"{progress.total} words · {progress.learned} learned "
                              f"({progress.mature} mature)")
        self.details.setObjectName("muted")
        bar = StackedBar(progress.mature, progress.young, progress.total)
        bar.setFixedHeight(6)
        bar.setMaximumWidth(360)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addLayout(top)
        left.addWidget(self.details)
        left.addWidget(bar)

        c = self.counts
        self.figures = {}
        right = QHBoxLayout()
        right.setSpacing(18)
        for key, number, label, colour, tip in (
                ("new", str(c.new), "new", GOOD, NEW_TIP),
                ("learning", learning_text(c), "learning", BAD, LEARNING_TIP),
                ("due", str(c.review), "due", "#1a202c", DUE_TIP)):
            box = QVBoxLayout()
            box.setSpacing(0)
            value = QLabel(number)
            value.setObjectName("deckFigure")
            value.setAlignment(Qt.AlignCenter)
            value.setStyleSheet(f"color: {colour if number not in ('0', '') else MUTED};")
            caption = QLabel(label)
            caption.setObjectName("muted")
            caption.setAlignment(Qt.AlignCenter)
            for part in (value, caption):
                part.setToolTip(tip)
            box.addWidget(value)
            box.addWidget(caption)
            right.addLayout(box)
            self.figures[key] = value
        self.study_btn = QPushButton("Study ›")
        self.study_btn.setObjectName("primary")
        self.study_btn.clicked.connect(lambda: self.study.emit(self.deck))
        right.addSpacing(6)
        right.addWidget(self.study_btn)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.addLayout(left, 1)
        row.addLayout(right)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.study.emit(self.deck)

class HomePage(QWidget):
    study_requested = Signal(object)   # Deck
    stats_requested = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store

        title = QLabel("Decks")
        title.setObjectName("title")
        self.summary = QLabel()
        self.summary.setObjectName("muted")

        # The decks, one card each, in a scroll area.
        self.cards: list[DeckCard] = []
        self._selected: int | None = None
        self.deck_list = QWidget()
        self.deck_list.setObjectName("deckList")
        self.cards_layout = QVBoxLayout(self.deck_list)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.deck_list)
        self.setFocusPolicy(Qt.StrongFocus)

        new_btn = QPushButton("New deck…")
        new_btn.clicked.connect(self.new_deck)
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self.edit_deck)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_deck)
        self.export_btn = QPushButton("Export…")
        self.export_btn.setToolTip("Save this deck as a file to share. Your progress is not included.")
        self.export_btn.clicked.connect(self.export_deck)
        import_btn = QPushButton("Import…")
        import_btn.setToolTip("Add a deck from a .vocabdeck file.")
        import_btn.clicked.connect(self.import_deck)

        buttons = QHBoxLayout()
        stats_btn = QPushButton("Statistics")
        stats_btn.clicked.connect(self.stats_requested.emit)
        buttons.addWidget(stats_btn)
        buttons.addStretch()
        buttons.addWidget(new_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.delete_btn)
        buttons.addSpacing(12)
        buttons.addWidget(self.export_btn)
        buttons.addWidget(import_btn)

        self.empty = QLabel("No decks yet. Click <b>New deck…</b> and choose "
                            "<i>Biblical Hebrew by frequency</i> to start with the most common words.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addWidget(title)
        layout.addWidget(self.summary)
        # Overview figures, the same as at the top of the statistics; rebuilt in refresh().
        self.overview_box = QVBoxLayout()
        self.overview_box.setContentsMargins(0, 2, 0, 6)
        layout.addLayout(self.overview_box)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.empty)
        layout.addLayout(buttons)
        self._decks: list[decks.Deck] = []

    def refresh(self) -> None:
        selected = self.selected_deck()
        self._decks = decks.list_decks(self.store)
        while self.cards_layout.count():
            old = self.cards_layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        self.cards = []
        for deck in self._decks:
            card = DeckCard(self.store, deck)
            card.clicked.connect(lambda c: self._select(self.cards.index(c)))
            card.study.connect(self.study_requested.emit)
            self.cards_layout.addWidget(card)
            self.cards.append(card)
        self.cards_layout.addStretch()
        self._selected = None
        if self._decks:
            self._select(next((i for i, d in enumerate(self._decks)
                               if selected and d.deck_id == selected.deck_id), 0))
        self.scroll.setVisible(bool(self._decks))
        self.empty.setVisible(not self._decks)

        maturity = stats._maturity(self.store)
        total_reviews = self.store.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        self.summary.setText(f"{len(maturity)} words learned ({sum(maturity.values())} mature) · "
                             f"{total_reviews} reviews in total")
        self.summary.setToolTip(f"Mature words have an interval of {stats.MATURE_DAYS} days or "
                                "more; see Statistics for details.")
        while self.overview_box.count():
            old = self.overview_box.takeAt(0).widget()
            if old is not None:
                old.setParent(None)          # gone at once, not only when Qt next idles
                old.deleteLater()
        self.overview = overview_tiles(self.store, compact=True)
        self.overview_box.addWidget(self.overview)
        self._update_buttons()

    def selected_deck(self) -> decks.Deck | None:
        if self._selected is not None and self._selected < len(self.cards):
            return self.cards[self._selected].deck
        return None

    def _select(self, index: int) -> None:
        self._selected = index
        for i, card in enumerate(self.cards):
            card.set_selected(i == index)
        if 0 <= index < len(self.cards):
            self.scroll.ensureWidgetVisible(self.cards[index])
        self._update_buttons()

    def keyPressEvent(self, event) -> None:
        if not self.cards:
            return super().keyPressEvent(event)
        current = self._selected or 0
        if event.key() == Qt.Key_Down:
            self._select(min(current + 1, len(self.cards) - 1))
        elif event.key() == Qt.Key_Up:
            self._select(max(current - 1, 0))
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.study()
        else:
            super().keyPressEvent(event)

    def _update_buttons(self) -> None:
        has = self.selected_deck() is not None
        for b in (self.edit_btn, self.delete_btn, self.export_btn):
            b.setEnabled(has)

    def study(self) -> None:
        deck = self.selected_deck()
        if deck:
            self.study_requested.emit(deck)

    def new_deck(self) -> None:
        dlg = DeckEditor(self.store, None, self)
        if dlg.exec():
            self.refresh()

    def edit_deck(self) -> None:
        deck = self.selected_deck()
        if deck and DeckEditor(self.store, deck, self).exec():
            self.refresh()

    def export_deck(self) -> None:
        deck = self.selected_deck()
        if not deck:
            return
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in deck.name).strip()
        path, _ = QFileDialog.getSaveFileName(self, "Export deck", f"{safe}{deckfile.EXTENSION}",
                                              f"Vocab decks (*{deckfile.EXTENSION})")
        if not path:
            return
        try:
            n = deckfile.export_deck(self.store, deck, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export deck", f"Could not save the file: {exc}")
            return
        own = f" It includes {n} of your own glosses." if n else ""
        QMessageBox.information(self, "Export deck",
                                f"The deck “{deck.name}” was saved.{own}\n\n"
                                "Your learning progress is not included.")

    def import_deck(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import deck", "",
                                              f"Vocab decks (*{deckfile.EXTENSION});;All files (*)")
        if path:
            self.import_deck_file(path)

    def import_deck_file(self, path: str) -> deckfile.DeckImport | None:
        try:
            result = deckfile.import_deck(self.store, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import deck", str(exc))
            return None
        lines = [f"Added the deck “{result.deck.name}” with {result.words} words."]
        if result.renamed:
            lines.append("(You already had a deck with that name, so a number was added.)")
        if result.glosses_added:
            lines.append(f"{result.glosses_added} glosses from the deck were added.")
        if result.glosses_kept:
            lines.append(f"{result.glosses_kept} of your own glosses were kept.")
        lines += result.warnings
        QMessageBox.information(self, "Import deck", "\n".join(lines))
        self.refresh()
        self.select_deck(result.deck.deck_id)
        return result

    def select_deck(self, deck_id: int) -> None:
        for i, card in enumerate(self.cards):
            if card.deck.deck_id == deck_id:
                self._select(i)

    def delete_deck(self) -> None:
        deck = self.selected_deck()
        if not deck:
            return
        answer = QMessageBox.question(
            self, "Delete deck",
            f"Delete the deck “{deck.name}”?\n\nYour progress on its words is kept and "
            "still counts in your other decks.")
        if answer == QMessageBox.Yes:
            decks.delete_deck(self.store, deck.deck_id)
            self.refresh()
