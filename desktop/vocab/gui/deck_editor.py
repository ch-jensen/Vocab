"""Dialog for creating or editing a deck."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import decks
from ..decks import Deck, DeckConfig, Passage
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
        self.books = checklist([(b, en) for b, en, _ in store.books()],
                               {p.book for p in cfg.passages} if cfg.passages else None, 150)
        self._chapters = {b: n for b, _, n in store.books()}
        self.ch_from = QSpinBox()
        self.ch_to = QSpinBox()
        for s in (self.ch_from, self.ch_to):
            s.setRange(1, 150)
        one = cfg.passages[0] if cfg.passages and len(cfg.passages) == 1 else None
        self.ch_from.setValue(one.chapter_from or 1 if one else 1)
        self.ch_to.setValue(one.chapter_to or 150 if one else 150)
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("chapters"))
        ch_row.addWidget(self.ch_from)
        ch_row.addWidget(QLabel("to"))
        ch_row.addWidget(self.ch_to)
        ch_row.addWidget(QLabel("(when one book is chosen)"))
        ch_row.addStretch()

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
        ff.addRow("Books", with_buttons(self.books))
        ff.addRow("", ch_row)

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
        self._timer = QTimer(self, singleShot=True, interval=300)
        self._timer.timeout.connect(self.update_count)
        for signal in (self.plan_radio.toggled, self.plan.currentIndexChanged,
                       self.hebrew.toggled, self.aramaic.toggled, self.rank_min.valueChanged,
                       self.rank_max.valueChanged, self.suffix.currentIndexChanged,
                       self.ch_from.valueChanged, self.ch_to.valueChanged,
                       self.gloss.currentIndexChanged, self.split.toggled):
            signal.connect(self._changed)
        for lw in (self.pos, self.stems, self.tenses, self.books):
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
        books = checked_values(self.books)
        passages = None
        if books is not None:
            if len(books) == 1:
                passages = [Passage(books[0], self.ch_from.value(),
                                    min(self.ch_to.value(), self._chapters[books[0]]))]
            else:
                passages = [Passage(b) for b in books]
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
        n = self.card_count()
        self.count.setText(f"{n} words in this deck")

    def save(self) -> None:
        name = self.name.text().strip()
        if not name:
            if self.plan_radio.isChecked():
                name = self.plan.currentText().rsplit(" (", 1)[0]
            else:
                QMessageBox.warning(self, "Name missing", "Please give the deck a name.")
                return
        cfg = self.config()
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
