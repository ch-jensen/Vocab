"""Dialog for creating or editing a deck."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import decks
from ..decks import (Deck, DeckConfig, Passage, format_chapters, parse_chapters,
                     passages_by_book)
from ..store import Store
from .common import POS_LABELS, TENSE_LABELS, stem_label

MAX_RANK = 9999


def checklist(items: list[tuple[str, str]], checked: set[str] | None, height: int = 150) -> QListWidget:
    """A list of (value, label) with checkboxes. checked=None means all checked."""
    lw = QListWidget()
    for value, label in items:
        it = QListWidgetItem(label)
        it.setData(Qt.UserRole, value)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked is None or value in checked else Qt.Unchecked)
        lw.addItem(it)
    lw.setMinimumHeight(height)
    return lw


def checked_values(lw: QListWidget) -> list[str] | None:
    """Checked values, or None if all are checked (= no restriction)."""
    values = [lw.item(i).data(Qt.UserRole) for i in range(lw.count())
              if lw.item(i).checkState() == Qt.Checked]
    return None if len(values) == lw.count() else values


def set_all(lw: QListWidget, state: bool) -> None:
    for i in range(lw.count()):
        lw.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)


def with_buttons(lw: QListWidget) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.addWidget(lw)
    row = QHBoxLayout()
    for text, state in (("All", True), ("None", False)):
        b = QLabel(f'<a href="#">{text}</a>')
        b.linkActivated.connect(lambda _=None, s=state: set_all(lw, s))
        row.addWidget(b)
    row.addStretch()
    v.addLayout(row)
    return w


class BookChapters(QWidget):
    """A table of books, each with a checkbox and its own chapters (e.g. '1-11, 37-50')."""

    changed = Signal()

    def __init__(self, books: list[tuple[str, str, int]], passages: list[Passage] | None,
                 parent=None):
        super().__init__(parent)
        self._books = books
        chosen = passages_by_book(passages)
        self.table = QTableWidget(len(books), 2)
        self.table.setHorizontalHeaderLabels(["Book", "Chapters, e.g. 1-3; 11; 45-48 (empty = whole book)"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(220)
        self.edits: list[QLineEdit] = []
        for row, (book, english, last) in enumerate(books):
            item = QTableWidgetItem(english)
            item.setData(Qt.UserRole, book)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if passages is None or book in chosen else Qt.Unchecked)
            self.table.setItem(row, 0, item)
            edit = QLineEdit()
            edit.setObjectName("chapters")
            edit.setPlaceholderText(f"1–{last}")
            edit.setToolTip(f"{english} has {last} chapters. Separate parts with semicolons, e.g. 1-3; 11; 45-48")
            if book in chosen:
                ranges = [(a, min(b, last)) for a, b in chosen[book]]
                edit.setText(format_chapters(ranges, last))
            edit.textEdited.connect(lambda _text, r=row: self._edited(r))
            self.table.setCellWidget(row, 1, edit)
            self.edits.append(edit)
        self.table.itemChanged.connect(lambda _item: self.changed.emit())

        links = QHBoxLayout()
        for text, state in (("All", True), ("None", False)):
            link = QLabel(f'<a href="#">{text}</a>')
            link.linkActivated.connect(lambda _=None, st=state: self.set_all(st))
            links.addWidget(link)
        links.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(links)

    def _edited(self, row: int) -> None:
        if self.edits[row].text().strip():
            self.table.item(row, 0).setCheckState(Qt.Checked)   # typing chapters selects the book
        self._validate(row)
        self.changed.emit()

    def _validate(self, row: int) -> str | None:
        _book, english, last = self._books[row]
        try:
            parse_chapters(self.edits[row].text(), last)
            self.edits[row].setStyleSheet("")
            return None
        except ValueError as exc:
            self.edits[row].setStyleSheet("QLineEdit#chapters { border: 2px solid #c53030; }")
            return f"{english}: {exc}"

    def set_all(self, state: bool) -> None:
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.Checked if state else Qt.Unchecked)
            if not state:
                self.edits[row].clear()
                self.edits[row].setStyleSheet("")
        self.table.blockSignals(False)
        self.changed.emit()

    def set_book(self, book: str, chapters: str = "", checked: bool = True) -> None:
        for row, (b, _, _) in enumerate(self._books):
            if b == book:
                self.table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.edits[row].setText(chapters)
                self._validate(row)

    def passages(self) -> list[Passage] | None:
        """The chosen passages, or None for the whole Bible. Raises ValueError for bad input."""
        out, whole = [], True
        for row, (book, _english, last) in enumerate(self._books):
            if self.table.item(row, 0).checkState() != Qt.Checked:
                whole = False
                continue
            error = self._validate(row)
            if error:
                raise ValueError(error)
            ranges = parse_chapters(self.edits[row].text(), last)
            if ranges != [(1, last)]:
                whole = False
            out += [Passage(book) if (a, b) == (1, last) else Passage(book, a, b)
                    for a, b in ranges]
        if whole:
            return None
        if not out:
            raise ValueError("Choose at least one book.")
        return out


class _CountSignals(QObject):
    done = Signal(int, object)      # generation, number of words or the exception


class _CountTask(QRunnable):
    """Counts a deck's words on a worker thread with its own read-only connection."""

    def __init__(self, store: Store, cfg: DeckConfig, generation: int, signals: _CountSignals):
        super().__init__()
        self.store, self.cfg, self.generation, self.signals = store, cfg, generation, signals

    def run(self) -> None:
        try:
            con = self.store.read_only_connection()
            try:
                result = len(decks.deck_cards(con, self.cfg))
            finally:
                con.close()
        except Exception as exc:     # shown in the dialog instead of crashing the app
            result = exc
        try:
            self.signals.done.emit(self.generation, result)
        except RuntimeError:         # the dialog was closed in the meantime
            pass


class DeckEditor(QDialog):
    def __init__(self, store: Store, deck: Deck | None, parent=None):
        super().__init__(parent)
        self.store = store
        self.deck = deck
        cfg = deck.config if deck else DeckConfig(plan_id="hebrew-frequency")
        self.setWindowTitle("Edit deck" if deck else "New deck")
        self.resize(620, 640)

        self.name = QLineEdit(deck.name if deck else "")
        self.name.setPlaceholderText("e.g. Hebrew by frequency")

        # --- Words tab -----------------------------------------------------
        self.plan_radio = QRadioButton("A predefined plan, from the most to the least frequent word")
        self.custom_radio = QRadioButton("My own selection")
        group = QButtonGroup(self)
        group.addButton(self.plan_radio)
        group.addButton(self.custom_radio)
        self.plan = QComboBox()
        for p in decks.plans(store):
            self.plan.addItem(f"{p['name']} ({p['size']} words)", p["plan_id"])
        if cfg.plan_id:
            self.plan.setCurrentIndex(max(self.plan.findData(cfg.plan_id), 0))
        (self.plan_radio if cfg.plan_id else self.custom_radio).setChecked(True)

        self.hebrew = QCheckBox("Hebrew")
        self.aramaic = QCheckBox("Aramaic")
        self.hebrew.setChecked("Hebrew" in cfg.languages)
        self.aramaic.setChecked("Aramaic" in cfg.languages)
        lang_row = QHBoxLayout()
        lang_row.addWidget(self.hebrew)
        lang_row.addWidget(self.aramaic)
        lang_row.addStretch()

        self.pos = checklist(list(POS_LABELS.items()), set(cfg.pos) if cfg.pos is not None else None)
        self.rank_min = QSpinBox()
        self.rank_max = QSpinBox()
        for s in (self.rank_min, self.rank_max):
            s.setRange(1, MAX_RANK)
        self.rank_min.setValue((cfg.rank_min or 0) + 1)
        self.rank_max.setValue(cfg.rank_max + 1 if cfg.rank_max is not None else MAX_RANK)
        rank_row = QHBoxLayout()
        rank_row.addWidget(QLabel("from"))
        rank_row.addWidget(self.rank_min)
        rank_row.addWidget(QLabel("to"))
        rank_row.addWidget(self.rank_max)
        rank_row.addWidget(QLabel("(1 = most frequent)"))
        rank_row.addStretch()

        self.custom_box = QGroupBox()
        cf = QFormLayout(self.custom_box)
        cf.addRow("Language", lang_row)
        cf.addRow("Part of speech", with_buttons(self.pos))
        cf.addRow("Frequency rank", rank_row)

        words = QWidget()
        wl = QVBoxLayout(words)
        wl.addWidget(self.plan_radio)
        wl.addWidget(self.plan)
        wl.addSpacing(8)
        wl.addWidget(self.custom_radio)
        wl.addWidget(self.custom_box)
        wl.addStretch()

        # --- Forms tab -----------------------------------------------------
        stems = [(s, f"{stem_label(s)} ({lang[:3]}., {n})") for s, lang, n in store.stems()]
        self.stems = checklist(stems, set(cfg.stems) if cfg.stems is not None else None)
        self.tenses = checklist(list(TENSE_LABELS.items()),
                                set(cfg.tenses) if cfg.tenses is not None else None, 120)
        self.suffix = QComboBox()
        for value, label in (("any", "with or without"), ("with", "only with a suffix"),
                             ("without", "only without a suffix")):
            self.suffix.addItem(label, value)
        self.suffix.setCurrentIndex(self.suffix.findData(cfg.suffix))
        self.books = BookChapters(store.books(), cfg.passages)

        forms = QWidget()
        ff = QFormLayout(forms)
        note = QLabel("Choose which attested forms you will be shown. Stem and tense only "
                      "apply to verbs. A word is in the deck if at least one of its forms is.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        ff.addRow(note)
        ff.addRow("Verbal stem", with_buttons(self.stems))
        ff.addRow("Tense", with_buttons(self.tenses))
        ff.addRow("Pronominal suffix", self.suffix)
        ff.addRow("Books and\nchapters", self.books)

        # --- Study tab -----------------------------------------------------
        self.gloss = QComboBox()
        for lang in store.gloss_languages():
            self.gloss.addItem(lang)
        self.gloss.setCurrentText(cfg.gloss_language)
        self.split = QCheckBox("Learn each verbal stem as a separate word (e.g. qal and piel)")
        self.split.setChecked(cfg.split_stems)
        self.mode = QComboBox()
        self.mode.addItem("Type the gloss", "typed")
        self.mode.addItem("Show the answer and rate yourself (like Anki)", "self")
        self.mode.setCurrentIndex(self.mode.findData(cfg.answer_mode))
        self.show_lex = QCheckBox("Show the dictionary form with the question")
        self.show_lex.setChecked(cfg.show_lexeme)
        self.new_per_day = QSpinBox()
        self.new_per_day.setRange(0, 9999)
        self.new_per_day.setValue(cfg.new_per_day)
        self.max_reviews = QSpinBox()
        self.max_reviews.setRange(0, 99999)
        self.max_reviews.setValue(cfg.max_reviews_per_day)
        self.retention = QDoubleSpinBox()
        self.retention.setRange(0.70, 0.97)
        self.retention.setSingleStep(0.01)
        self.retention.setValue(cfg.desired_retention)

        study = QWidget()
        sf = QFormLayout(study)
        sf.addRow("Gloss language", self.gloss)
        sf.addRow("", self.split)
        sf.addRow("Answer", self.mode)
        sf.addRow("", self.show_lex)
        sf.addRow("New words per day", self.new_per_day)
        sf.addRow("Maximum reviews per day", self.max_reviews)
        ret_note = QLabel("The chance of remembering a word when it comes up. Higher means "
                          "more reviews; 0.90 is Anki's default.")
        ret_note.setWordWrap(True)
        ret_note.setObjectName("muted")
        sf.addRow("Desired retention", self.retention)
        sf.addRow("", ret_note)

        tabs = QTabWidget()
        tabs.addTab(words, "Words")
        tabs.addTab(forms, "Forms")
        tabs.addTab(study, "Study")

        self.count = QLabel()
        self.count.setObjectName("muted")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.count)
        bottom.addStretch()
        bottom.addWidget(buttons)

        form = QFormLayout()
        form.addRow("Name", self.name)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom)

        # Live count of words in the deck.
        self._generation = 0
        self._count_signals = _CountSignals()
        self._count_signals.done.connect(self._count_done)
        self._timer = QTimer(self, singleShot=True, interval=300)
        self._timer.timeout.connect(self.update_count)
        for signal in (self.plan_radio.toggled, self.plan.currentIndexChanged,
                       self.hebrew.toggled, self.aramaic.toggled, self.rank_min.valueChanged,
                       self.rank_max.valueChanged, self.suffix.currentIndexChanged,
                       self.books.changed,
                       self.gloss.currentIndexChanged, self.split.toggled):
            signal.connect(self._changed)
        for lw in (self.pos, self.stems, self.tenses):
            lw.itemChanged.connect(self._changed)
        self._changed()

    def _changed(self, *_):
        self.custom_box.setEnabled(self.custom_radio.isChecked())
        self.plan.setEnabled(self.plan_radio.isChecked())
        self._timer.start()

    def config(self) -> DeckConfig:
        plan_id = self.plan.currentData() if self.plan_radio.isChecked() else None
        if plan_id:
            languages, pos, rank_min, rank_max = ["Hebrew", "Aramaic"], None, None, None
        else:
            languages = [l for l, cb in (("Hebrew", self.hebrew), ("Aramaic", self.aramaic))
                         if cb.isChecked()]
            pos = checked_values(self.pos)
            rank_min = self.rank_min.value() - 1 if self.rank_min.value() > 1 else None
            rank_max = self.rank_max.value() - 1 if self.rank_max.value() < MAX_RANK else None
        passages = self.books.passages()       # raises ValueError for bad chapter input
        return DeckConfig(
            plan_id=plan_id, languages=languages, pos=pos, rank_min=rank_min, rank_max=rank_max,
            stems=checked_values(self.stems), tenses=checked_values(self.tenses),
            suffix=self.suffix.currentData(), passages=passages,
            include_lex=self.deck.config.include_lex if self.deck else [],
            exclude_lex=self.deck.config.exclude_lex if self.deck else [],
            split_stems=self.split.isChecked(), gloss_language=self.gloss.currentText(),
            new_per_day=self.new_per_day.value(), max_reviews_per_day=self.max_reviews.value(),
            desired_retention=round(self.retention.value(), 2),
            answer_mode=self.mode.currentData(), show_lexeme=self.show_lex.isChecked(),
        )

    def card_count(self) -> int:
        return len(decks.deck_cards(self.store.con, self.config()))

    def update_count(self) -> None:
        """Count the deck's words in the background, so the dialog never freezes."""
        try:
            cfg = self.config()
        except ValueError as exc:
            self.count.setText(f'<span style="color:#c53030">{exc}</span>')
            return
        self._generation += 1
        self.count.setText("Counting words…")
        QThreadPool.globalInstance().start(
            _CountTask(self.store, cfg, self._generation, self._count_signals))

    def _count_done(self, generation: int, result) -> None:
        if generation != self._generation:
            return                                  # settings changed since; a newer count follows
        if isinstance(result, Exception):
            self.count.setText(f'<span style="color:#c53030">Could not count the words: {result}</span>')
        else:
            self.count.setText(f"{result} words in this deck")

    def save(self) -> None:
        name = self.name.text().strip()
        if not name:
            if self.plan_radio.isChecked():
                name = self.plan.currentText().rsplit(" (", 1)[0]
            else:
                QMessageBox.warning(self, "Name missing", "Please give the deck a name.")
                return
        try:
            cfg = self.config()
        except ValueError as exc:
            QMessageBox.warning(self, "Chapters", str(exc))
            return
        if self.card_count() == 0:
            QMessageBox.warning(self, "Empty deck", "No words match these settings.")
            return
        existing = decks.get_deck(self.store, name)
        if existing and (not self.deck or existing.deck_id != self.deck.deck_id):
            QMessageBox.warning(self, "Name in use", f"There is already a deck called “{name}”.")
            return
        if self.deck:
            self.deck.name, self.deck.config = name, cfg
            decks.update_deck(self.store, self.deck)
        else:
            self.deck = decks.create_deck(self.store, name, cfg)
        self.accept()
