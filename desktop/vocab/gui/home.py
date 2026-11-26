"""Home screen: the list of decks with today's counts."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import decks
from ..session import StudySession
from ..store import Store
from .common import BAD, GOOD
from .deck_editor import DeckEditor


class HomePage(QWidget):
    study_requested = Signal(object)   # Deck

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

        buttons = QHBoxLayout()
        buttons.addWidget(self.study_btn)
        buttons.addStretch()
        buttons.addWidget(new_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.delete_btn)

        self.empty = QLabel("No decks yet. Click <b>New deck…</b> and choose "
                            "<i>Biblical Hebrew by frequency</i> to start with the most common words.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addWidget(title)
        layout.addWidget(self.summary)
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
            cells = [deck.name, str(c.new), str(c.learning), str(c.review)]
            colours = [None, GOOD, BAD, None]
            for col, (text, colour) in enumerate(zip(cells, colours)):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignCenter)
                if colour and text != "0":
                    item.setForeground(QColor(colour))
                self.table.setItem(row, col, item)
        if self._decks:
            index = next((i for i, d in enumerate(self._decks)
                          if selected and d.deck_id == selected.deck_id), 0)
            self.table.selectRow(index)
        self.table.setVisible(bool(self._decks))
        self.empty.setVisible(not self._decks)

        learned, total_reviews = self.store.con.execute(
            "SELECT (SELECT COUNT(*) FROM cards WHERE state = 2), (SELECT COUNT(*) FROM reviews)"
        ).fetchone()
        self.summary.setText(f"{learned} words learned · {total_reviews} reviews in total")
        self._update_buttons()

    def selected_deck(self) -> decks.Deck | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows and rows[0].row() < len(self._decks):
            return self._decks[rows[0].row()]
        return None

    def _update_buttons(self) -> None:
        has = self.selected_deck() is not None
        for b in (self.study_btn, self.edit_btn, self.delete_btn):
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
