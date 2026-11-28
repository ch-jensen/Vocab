"""The three study counts (new / learning / due) with explanations on hover."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..session import Counts
from .common import BAD, GOOD

NEW_TIP = ("<b>New</b>: words you haven't seen yet. The number is how many you will still "
           "get today (at most the deck's daily limit).")
LEARNING_TIP = ("<b>Learning</b>: words you have met or forgotten today. They come back "
                "after short steps (1 min, then 10 min) until they graduate.<br>"
                "The first number counts those due now; the number in parentheses counts "
                "those waiting to come back later today.")
DUE_TIP = ("<b>Due</b>: everything waiting for you from earlier days: learned words whose "
           "interval (days to months) runs out today, and words left in learning since an "
           "earlier day. Forget one and it goes back to learning.")


def learning_text(c: Counts) -> str:
    """'2', or '2 (+3)' when 3 more words in learning come back later today."""
    return f"{c.learning} (+{c.learning_later})" if c.learning_later else str(c.learning)


class CountsBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.new = QLabel()
        self.learning = QLabel()
        self.due = QLabel()
        for label, tip, colour in ((self.new, NEW_TIP, GOOD), (self.learning, LEARNING_TIP, BAD),
                                   (self.due, DUE_TIP, None)):
            label.setToolTip(tip)
            label.setCursor(Qt.WhatsThisCursor)
            if colour:
                label.setStyleSheet(f"color: {colour};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for i, label in enumerate((self.new, self.learning, self.due)):
            if i:
                layout.addWidget(QLabel("·"))
            layout.addWidget(label)

    def set_counts(self, c: Counts, current: str | None = None) -> None:
        """Show the counts; `current` ('new', 'learning' or 'due') is underlined, as in Anki,
        to show which group the word on screen comes from."""
        self.new.setText(f"{c.new} new")
        self.learning.setText(f"{learning_text(c)} learning")
        self.due.setText(f"{c.review} due")
        for group, label in (("new", self.new), ("learning", self.learning), ("due", self.due)):
            font = label.font()
            font.setUnderline(group == current)
            label.setFont(font)

    def current(self) -> str | None:
        """The underlined group, if any."""
        for group, label in (("new", self.new), ("learning", self.learning), ("due", self.due)):
            if label.font().underline():
                return group
        return None
