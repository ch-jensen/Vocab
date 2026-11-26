"""Study screen: one attested occurrence in its clause, answer, feedback, next."""

from __future__ import annotations

import html

from fsrs import Rating
from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..decks import Deck
from ..answers import split_glosses
from ..session import Outcome, StudyItem, StudySession, expected_gloss
from ..store import Store
from .counts import CountsBar
from .gloss_dialog import GlossDialog
from .common import (ACCENT, BAD, GOOD, MUTED, POS_LABELS, TENSE_LABELS, hebrew_font,
                     interval_text, stem_label)

RATING_LABELS = {Rating.Again: "Again", Rating.Hard: "Hard", Rating.Good: "Good", Rating.Easy: "Easy"}


def clause_html(item: StudyItem) -> str:
    parts = []
    for w in item.clause:
        form = html.escape(w.form)
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
        self.counts = CountsBar()
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
        self.facts.linkActivated.connect(self._link)
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

        # "Finished for now" panel
        self.done_title = QLabel()
        self.done_title.setAlignment(Qt.AlignCenter)
        self.done_title.setObjectName("title")
        self.done_text = QLabel()
        self.done_text.setAlignment(Qt.AlignCenter)
        self.done_text.setWordWrap(True)
        self.continue_btn = QPushButton()
        self.continue_btn.clicked.connect(self.next_card)
        done_back = QPushButton("Back to decks")
        done_back.clicked.connect(self.finished.emit)
        done_row = QHBoxLayout()
        done_row.addStretch()
        done_row.addWidget(self.continue_btn)
        done_row.addWidget(done_back)
        done_row.addStretch()
        self.done = QWidget()
        done_layout = QVBoxLayout(self.done)
        done_layout.addWidget(self.done_title)
        done_layout.addWidget(self.done_text)
        done_layout.addSpacing(16)
        done_layout.addLayout(done_row)
        layout.insertWidget(layout.indexOf(self.clause), self.done)
        self.done.hide()
        # When words in learning become due, the Continue button is enabled.
        self.wait_timer = QTimer(self, singleShot=True)
        self.wait_timer.timeout.connect(self._learning_due)
        self.finished.connect(self.wait_timer.stop)

        # Keyboard
        # All keys are handled in keyPressEvent. The answer box and the buttons
        # pass Return/Enter on to this page, so it must be handled in one place
        # only: handling it in QLineEdit.returnPressed as well would submit the
        # answer and then skip straight to the next word.

    # --- flow ----------------------------------------------------------------
    def start(self, deck: Deck) -> None:
        self.session = StudySession(self.store, deck)
        self.deck_label.setText(deck.name)
        self.next_card()

    def _set_counts(self) -> None:
        self.counts.set_counts(self.session.counts())

    def next_card(self) -> None:
        self._set_counts()
        self.item = self.session.next_item()
        self.answered = False
        self.feedback.clear()
        self.facts.clear()
        self.wait_timer.stop()
        if self.item is None:
            self._show_done()
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

    def _show_done(self) -> None:
        for w in (self.clause, self.reference, self.lexeme_hint, self.controls):
            w.hide()
        self.done.show()
        waiting = self.session.next_learning_due()
        if waiting is None:
            self.done_title.setText("Congratulations!")
            self.done_text.setText("You have finished this deck for today.")
            self.continue_btn.hide()
            return
        due, n = waiting
        words = "1 word" if n == 1 else f"{n} words"
        self.done_title.setText("Finished for now")
        self.done_text.setText(
            f"{words} in learning will be due again later today, the first in "
            f"{interval_text(due)} (at {due.astimezone().strftime('%H:%M')}).<br>"
            f'<span style="color:{MUTED}">You can come back then, or wait here.</span>')
        self.continue_btn.setText("Continue")
        self.continue_btn.setEnabled(False)
        self.continue_btn.show()
        wait_ms = max(int((due - self.session.clock()).total_seconds() * 1000), 0) + 500
        self.wait_timer.start(wait_ms)

    def _learning_due(self) -> None:
        self._set_counts()
        self.continue_btn.setEnabled(True)
        self.continue_btn.setText("Continue  (Enter)")
        self.continue_btn.setFocus()
        self.done_text.setText("Words in learning are due again.")

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
        # As in Anki: the gloss was already shown, so rating goes straight on.
        self.session.rate(self.item, rating, self._elapsed())
        self.next_card()

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
        lines.append(f'<a href="edit-gloss">Edit gloss ({html.escape(self.session.cfg.gloss_language)})…</a>')
        self.facts.setText("<br>".join(lines))
        self._outcome = outcome

    def _link(self, href: str) -> None:
        if href == "edit-gloss" and self.item is not None:
            self.edit_gloss()

    def edit_gloss(self) -> None:
        item = self.item
        language = self.session.cfg.gloss_language
        if not GlossDialog(self.store, item.key.lex_id, language, self).exec():
            return
        item.gloss = expected_gloss(self.store.glosses(item.key.lex_id, language),
                                    item.stem, item.key.stem)
        item.expected = split_glosses(item.gloss)
        if self.controls.currentIndex() == 3:       # typed answer already graded
            self.feedback.setText(f'<span style="font-size:16pt;">{html.escape(item.gloss)}</span>'
                                  f'<br><span style="color:{MUTED}">Gloss updated.</span>')
        else:
            self.feedback.setText(f'<span style="font-size:18pt;">{html.escape(item.gloss)}</span>')
        self._show_facts(self._outcome)

    # --- keys ------------------------------------------------------------------
    def _enter(self) -> None:
        if self.item is None:
            if self.continue_btn.isVisible() and self.continue_btn.isEnabled():
                self.next_card()
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
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self._enter()
        elif key == Qt.Key_Escape:
            self.finished.emit()
        elif Qt.Key_1 <= key <= Qt.Key_4 and self.controls.currentIndex() == 2:
            self.rate(Rating(key - Qt.Key_1 + 1))   # digits typed in the answer box never get here
        else:
            super().keyPressEvent(event)

