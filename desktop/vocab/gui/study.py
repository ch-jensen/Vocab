"""Study screen: one attested occurrence in its clause, answer, feedback, next."""

from __future__ import annotations

import html

from fsrs import Rating
from PySide6.QtCore import QElapsedTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..decks import Deck
from ..session import Outcome, StudyItem, StudySession
from ..store import Store
from .common import (ACCENT, BAD, GOOD, MUTED, POS_LABELS, TENSE_LABELS, hebrew_font,
                     interval_text, stem_label)

RATING_LABELS = {Rating.Again: "Again", Rating.Hard: "Hard", Rating.Good: "Good", Rating.Easy: "Easy"}


def clause_html(item: StudyItem) -> str:
    parts = []
    for w in item.clause:
        # A word read but not written (qere without ketiv) is shown in brackets.
        form = html.escape(w.form) if w.form or not w.qere else f"[{html.escape(w.qere)}]"
        if w.node == item.node:
            form = f'<span style="color:{ACCENT}; font-weight:bold;">{form}</span>'
        parts.append(form + html.escape(w.trailer))
    return f'<div dir="rtl" align="center">{"".join(parts)}</div>'


class StudyPage(QWidget):
    finished = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.session: StudySession | None = None
        self.item: StudyItem | None = None
        self.timer = QElapsedTimer()
        self.answered = False

        # Header
        back = QPushButton("← Decks")
        back.setFlat(True)
        back.clicked.connect(self.finished.emit)
        self.deck_label = QLabel()
        self.deck_label.setObjectName("subtitle")
        self.counts = QLabel()
        self.counts.setTextFormat(Qt.RichText)
        header = QHBoxLayout()
        header.addWidget(back)
        header.addWidget(self.deck_label)
        header.addStretch()
        header.addWidget(self.counts)

        # Question
        self.clause = QLabel()
        self.clause.setFont(hebrew_font(30))
        self.clause.setTextFormat(Qt.RichText)
        self.clause.setWordWrap(True)
        self.clause.setAlignment(Qt.AlignCenter)
        self.clause.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.clause.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.reference = QLabel()
        self.reference.setAlignment(Qt.AlignCenter)
        self.reference.setObjectName("muted")
        self.lexeme_hint = QLabel()
        self.lexeme_hint.setFont(hebrew_font(18))
        self.lexeme_hint.setAlignment(Qt.AlignCenter)

        # Answer area: typed or self-graded
        self.answer = QLineEdit()
        self.answer.setPlaceholderText("Type the gloss and press Enter (empty = I don't know)")
        self.answer.returnPressed.connect(self._enter)
        self.answer.setMinimumWidth(380)
        typed_row = QHBoxLayout()
        typed_row.addStretch()
        typed_row.addWidget(self.answer)
        typed_row.addStretch()
        typed = QWidget()
        typed.setLayout(typed_row)

        self.show_btn = QPushButton("Show answer  (Space)")
        self.show_btn.clicked.connect(self.reveal)
        show_row = QHBoxLayout()
        show_row.addStretch()
        show_row.addWidget(self.show_btn)
        show_row.addStretch()
        show = QWidget()
        show.setLayout(show_row)

        self.rate_buttons: dict[Rating, QPushButton] = {}
        rate_row = QHBoxLayout()
        rate_row.addStretch()
        for rating in Rating:
            b = QPushButton()
            b.setMinimumWidth(110)
            b.clicked.connect(lambda _=False, r=rating: self.rate(r))
            self.rate_buttons[rating] = b
            rate_row.addWidget(b)
        rate_row.addStretch()
        rate = QWidget()
        rate.setLayout(rate_row)

        self.next_btn = QPushButton("Next  (Enter)")
        self.next_btn.clicked.connect(self.next_card)
        next_row = QHBoxLayout()
        next_row.addStretch()
        next_row.addWidget(self.next_btn)
        next_row.addStretch()
        nxt = QWidget()
        nxt.setLayout(next_row)

        self.controls = QStackedWidget()
        for w in (typed, show, rate, nxt):
            self.controls.addWidget(w)
        self.controls.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Feedback
        self.feedback = QLabel()
        self.feedback.setAlignment(Qt.AlignCenter)
        self.feedback.setTextFormat(Qt.RichText)
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName("feedback")
        self.facts = QLabel()
        self.facts.setAlignment(Qt.AlignCenter)
        self.facts.setTextFormat(Qt.RichText)
        self.facts.setWordWrap(True)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("rule")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.addLayout(header)
        layout.addWidget(line)
        layout.addStretch(2)
        layout.addWidget(self.clause)
        layout.addWidget(self.reference)
        layout.addWidget(self.lexeme_hint)
        layout.addSpacing(24)
        layout.addWidget(self.controls)
        layout.addSpacing(12)
        layout.addWidget(self.feedback)
        layout.addWidget(self.facts)
        layout.addStretch(3)

        self.done = QLabel()
        self.done.setAlignment(Qt.AlignCenter)
        self.done.setObjectName("subtitle")
        layout.addWidget(self.done)

        # Keyboard
        # Return/Enter in the answer box comes through returnPressed; elsewhere
        # through keyPressEvent (buttons outside dialogs pass Return on).
        # Space on a focused button clicks it.
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.finished.emit)
        for i, rating in enumerate(Rating, start=1):
            QShortcut(QKeySequence(str(i)), self, lambda r=rating: self._rate_key(r))

    # --- flow ----------------------------------------------------------------
    def start(self, deck: Deck) -> None:
        self.session = StudySession(self.store, deck)
        self.deck_label.setText(deck.name)
        self.next_card()

    def _set_counts(self) -> None:
        c = self.session.counts()
        self.counts.setText(f'<span style="color:{GOOD}">{c.new} new</span> · '
                            f'<span style="color:{BAD}">{c.learning} learning</span> · '
                            f'{c.review} due')

    def next_card(self) -> None:
        self._set_counts()
        self.item = self.session.next_item()
        self.answered = False
        self.feedback.clear()
        self.facts.clear()
        if self.item is None:
            for w in (self.clause, self.reference, self.lexeme_hint, self.controls):
                w.hide()
            self.done.setText("Well done! Nothing more to study in this deck today.")
            self.done.show()
            return
        self.done.hide()
        for w in (self.clause, self.reference, self.controls):
            w.show()
        item = self.item
        self.clause.setText(clause_html(item))
        new = f' · <span style="color:{GOOD}">new word</span>' if item.is_new else ""
        self.reference.setTextFormat(Qt.RichText)
        self.reference.setText(html.escape(item.reference) + new)
        self.lexeme_hint.setText(item.voc_lex_utf8)
        self.lexeme_hint.setVisible(self.session.cfg.show_lexeme)
        if self.session.cfg.answer_mode == "self":
            self.controls.setCurrentIndex(1)
            self.show_btn.setFocus()
        else:
            self.controls.setCurrentIndex(0)
            self.answer.clear()
            self.answer.setFocus()
        self.timer.start()

    def _elapsed(self) -> int:
        return int(self.timer.elapsed())

    def submit(self) -> None:
        if self.item is None or self.answered:
            return
        outcome = self.session.answer(self.item, self.answer.text(), self._elapsed())
        r = outcome.result
        gloss = html.escape(self.item.gloss or "(no gloss)")
        if r.correct:
            extra = " (small typo)" if r.typo else ""
            self.feedback.setText(f'<span style="color:{GOOD}; font-size:18pt;">✓ Correct{extra}</span>'
                                  f'<br><span style="font-size:16pt;">{gloss}</span>')
        else:
            given = html.escape(self.answer.text().strip())
            yours = f'<br><span style="color:{MUTED}">You wrote: {given}</span>' if given else ""
            self.feedback.setText(f'<span style="color:{BAD}; font-size:18pt;">✗ {gloss}</span>{yours}')
        self._after_answer(outcome)

    def reveal(self) -> None:
        if self.item is None or self.controls.currentIndex() != 1:
            return
        self.feedback.setText(f'<span style="font-size:18pt;">{html.escape(self.item.gloss)}</span>')
        self._show_facts()
        preview = self.session.preview(self.item)
        for rating, button in self.rate_buttons.items():
            button.setText(f"{RATING_LABELS[rating]}  ({rating.value})\n{interval_text(preview[rating])}")
        self.controls.setCurrentIndex(2)
        self.rate_buttons[Rating.Good].setFocus()

    def rate(self, rating: Rating) -> None:
        if self.item is None or self.answered or self.controls.currentIndex() != 2:
            return
        outcome = self.session.rate(self.item, rating, self._elapsed())
        self._after_answer(outcome)

    def _after_answer(self, outcome: Outcome) -> None:
        self.answered = True
        self._show_facts(outcome)
        self.controls.setCurrentIndex(3)
        self.next_btn.setFocus()
        self._set_counts()

    def _show_facts(self, outcome: Outcome | None = None) -> None:
        item = self.item
        self.lexeme_hint.setText(item.voc_lex_utf8)
        self.lexeme_hint.show()
        lines = [f'{POS_LABELS.get(item.sp, item.sp)} · {item.freq}× in the Bible · '
                 f'frequency rank {item.rank + 1}']
        if item.stem != "NA":
            form = f"this form: {stem_label(item.stem)} {TENSE_LABELS.get(item.tense, item.tense)}"
            stems = ", ".join(f"{stem_label(s)} {n}" for s, n in self.store.stem_counts(item.key.lex_id))
            lines.append(f'<span style="color:{MUTED}">{form} · stems: {stems}</span>')
        if outcome is not None:
            lines.append(f'<span style="color:{MUTED}">{RATING_LABELS[outcome.rating]} → '
                         f'next time in {interval_text(outcome.due)}</span>')
        self.facts.setText("<br>".join(lines))

    # --- keys ------------------------------------------------------------------
    def _enter(self) -> None:
        if self.item is None:
            return
        page = self.controls.currentIndex()
        if page == 0:
            self.submit()
        elif page == 1:
            self.reveal()
        elif page == 2:
            self.rate(Rating.Good)
        else:
            self.next_card()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.isAutoRepeat():
            self._enter()
        else:
            super().keyPressEvent(event)

    def _rate_key(self, rating: Rating) -> None:
        if self.controls.currentIndex() == 2:
            self.rate(rating)
