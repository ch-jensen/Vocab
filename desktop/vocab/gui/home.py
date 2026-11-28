"""Home screen: the list of decks with today's counts."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import deckfile, decks, stats
from ..session import StudySession
from ..store import Store
from .common import BAD, GOOD
from .counts import DUE_TIP, LEARNING_TIP, NEW_TIP, learning_text
from .deck_editor import DeckEditor
from .stats_page import overview_tiles


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

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Deck", "New", "Learning", "Due"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, 110)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        for col, tip in ((1, NEW_TIP), (2, LEARNING_TIP), (3, DUE_TIP)):
            self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.study)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.study_btn = QPushButton("Study")
        self.study_btn.setDefault(True)
        self.study_btn.clicked.connect(self.study)
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
        buttons.addWidget(self.study_btn)
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
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addLayout(buttons)
        self._decks: list[decks.Deck] = []

    def refresh(self) -> None:
        selected = self.selected_deck()
        self._decks = decks.list_decks(self.store)
        self.table.setRowCount(len(self._decks))
        for row, deck in enumerate(self._decks):
            c = StudySession(self.store, deck).counts()
            cells = [deck.name, str(c.new), learning_text(c), str(c.review)]
            colours = [None, GOOD, BAD, None]
            for col, (text, colour) in enumerate(zip(cells, colours)):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignCenter)
                if col:
                    item.setToolTip((NEW_TIP, LEARNING_TIP, DUE_TIP)[col - 1])
                if colour and text != "0":
                    item.setForeground(QColor(colour))
                self.table.setItem(row, col, item)
        if self._decks:
            index = next((i for i, d in enumerate(self._decks)
                          if selected and d.deck_id == selected.deck_id), 0)
            self.table.selectRow(index)
        self.table.setVisible(bool(self._decks))
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
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows and rows[0].row() < len(self._decks):
            return self._decks[rows[0].row()]
        return None

    def _update_buttons(self) -> None:
        has = self.selected_deck() is not None
        for b in (self.study_btn, self.edit_btn, self.delete_btn, self.export_btn):
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
        for row, deck in enumerate(self._decks):
            if deck.deck_id == deck_id:
                self.table.selectRow(row)

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
