"""The three study counts (new / learning / due) with explanations on hover."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..session import Counts
from .common import BAD, GOOD

NEW_TIP = ("<b>New</b>: words you haven't seen yet. The number is how many you will still "
           "get today (at most the deck's daily limit).")
LEARNING_TIP = ("<b>Learning</b>: words you have just met or just forgotten. They come back "
                "after short steps (1 min, then 10 min) until they graduate.<br>"
                "The first number counts those due now; the number in parentheses also "
                "counts those coming back later today.")
DUE_TIP = ("<b>Due</b>: words you have learned whose interval (days to months) has run out, "
           "so they are up for review today. Forget one and it goes back to learning.")


def learning_text(c: Counts) -> str:
    """'2' or '2 (5)' when more words in learning come back later today."""
    return f"{c.learning} ({c.learning_today})" if c.learning_today > c.learning else str(c.learning)


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

    def set_counts(self, c: Counts) -> None:
        self.new.setText(f"{c.new} new")
        self.learning.setText(f"{learning_text(c)} learning")
        self.due.setText(f"{c.review} due")
