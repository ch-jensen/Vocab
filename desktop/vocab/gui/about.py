"""The About window: the idea behind Vocab, how studying works, and the licence."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTabWidget,
                               QTextBrowser, QVBoxLayout)

from .. import __version__
from ..answers import (DEFAULT_REFERENCE_MS, FAST_FACTOR, MAX_REFERENCE_MS, MIN_REFERENCE_MS,
                       SLOW_FACTOR)
from ..optimize import MIN_REVIEWS
from ..stats import MATURE_DAYS
from ..store import APP_ROOT, DAY_ROLLOVER_HOUR

AUTHOR = "Christian Canu Højgaard"
YEARS = "2020–2026"

STYLE = """
<style>
  h2 { font-size: 15pt; margin-top: 14px; margin-bottom: 4px; }
  p, li { font-size: 11pt; line-height: 135%; }
  td, th { font-size: 11pt; padding: 3px 8px; vertical-align: top; }
  th { text-align: left; }
  .muted { color: #718096; }
</style>
"""

IDEA = STYLE + f"""
<h2>The idea</h2>
<p>Vocab brings together two things: a <b>flash card approach</b> to learning vocabulary, and
the <b>actual text of the Hebrew Bible</b>.</p>
<p><b>Flash cards with spaced repetition.</b> As with paper flash cards, you see a word and try
to recall its meaning. The difference is that Vocab keeps track of how well you know each word
and shows it again just before you would forget it: a new or difficult word comes back after a
few minutes, a well-known word only after weeks or months. Your study time goes to the words that
need it. The method is the one used by popular flash card programs such as Anki, and the
scheduling is done with FSRS, the same algorithm Anki uses.</p>
<p><b>Words as they occur in the text.</b> Ordinary flash cards show the dictionary form of a
word. Vocab instead shows each word <b>as it is written in a real verse</b> of the Hebrew Bible,
with its prefixes, suffixes and vowels, and in its clause. Each time, it picks another place where
the word occurs, so you learn to recognise it the way you will meet it when reading. This is
possible thanks to the BHSA (Biblia Hebraica Stuttgartensia Amstelodamensis), a database of the
Hebrew Bible made by the Eep Talstra Centre for Bible and Computer (ETCBC) in Amsterdam, in which
every word is analysed.</p>

<h2>What Vocab can do</h2>
<ul>
  <li><b>Attested forms in context.</b> Every review shows a different occurrence from the Hebrew
      Bible, forms you haven't seen first. Qere/ketiv cases are not asked about.</li>
  <li><b>Decks.</b> Predefined plans from the most to the least frequent word (Hebrew, or
      Aramaic), or your own selection by part of speech, frequency, verbal stem, tense, suffix,
      and books with chapters (e.g. Genesis 1-3; 11; 45-48). Each verbal stem can optionally be
      learned as a word of its own. Progress is shared between decks.</li>
  <li><b>Two ways to answer.</b> Type the gloss, or show the answer and rate yourself as in
      Anki.</li>
  <li><b>Statistics.</b> How much of the text of each book you know, young and mature words,
      retention, your progress per deck, and the reviews coming up.</li>
  <li><b>Personal scheduling.</b> After {MIN_REVIEWS} reviews, FSRS can be fitted to your own
      answers.</li>
  <li><b>Glosses.</b> English and Danish are included. Edit any gloss while studying, or import
      a gloss file in another language.</li>
  <li><b>Sharing.</b> Export a deck (with your own glosses, without your progress) and import
      decks from others. Progress from the notebook version can be imported too.</li>
</ul>
"""

HOW = STYLE + f"""
<h2>New, learning and due</h2>
<table>
  <tr><th>New</th><td>Words you haven't seen yet, up to the deck's daily limit.</td></tr>
  <tr><th>Learning</th><td>Words you met or forgot today. They come back after short steps
      (1 minute, then 10 minutes) until they <i>graduate</i>. The number in parentheses counts
      those coming back later today.</td></tr>
  <tr><th>Due</th><td>Everything waiting from earlier days: learned words whose interval runs
      out today, and words left in learning since an earlier day.</td></tr>
</table>
<p>The study day starts at {DAY_ROLLOVER_HOUR:02d}:00. Learned words are scheduled to a day, so
all of a day's reviews are available from the morning. When nothing is due, the session ends;
words still in learning come back later the same day. Learned words with an interval of
{MATURE_DAYS} days or more count as <b>mature</b>, the others as <b>young</b>.</p>

<h2>How typed answers are rated</h2>
<p>First Vocab checks <b>whether</b> the answer is right, then <b>how quickly</b> it was given.</p>
<p>An answer is right if it matches one of the listed glosses for the form shown. Capital
letters, punctuation, text in parentheses and a leading <i>to</i>, <i>the</i> or <i>a</i> are
ignored, and a small typo is forgiven (one letter in words of 4–7 letters, two in longer
words).</p>
<table>
  <tr><th>Wrong, or empty (= I don't know)</th><td><b>Again</b></td></tr>
  <tr><th>Right, with a small typo</th><td><b>Hard</b></td></tr>
  <tr><th>Right, but slower than {SLOW_FACTOR:g} × your usual time</th><td><b>Hard</b></td></tr>
  <tr><th>Right, and faster than {FAST_FACTOR:g} × your usual time</th>
      <td><b>Easy</b> (never the first time you see a word)</td></tr>
  <tr><th>Right otherwise</th><td><b>Good</b></td></tr>
</table>
<p>The time runs from when the word appears until you press Enter. <i>Your usual time</i> is the
median of your last 100 right typed answers, so it adapts to how fast you read and type. Until
you have 10 of them, Vocab assumes {DEFAULT_REFERENCE_MS / 1000:g} seconds; it always stays
between {MIN_REFERENCE_MS / 1000:g} and {MAX_REFERENCE_MS / 1000:g} seconds.</p>

<h2>Rating yourself</h2>
<p>In self-rated mode you show the answer and choose <b>Again</b> (forgot it), <b>Hard</b>,
<b>Good</b> or <b>Easy</b> with the mouse or the keys 1–4. Each button shows when the word would
come back, and the next word follows at once.</p>

<h2>What the rating does</h2>
<p><b>Again</b> sends a word back to learning. <b>Hard</b>, <b>Good</b> and <b>Easy</b> give
growing intervals: FSRS estimates how stable your memory of the word is and schedules it for when
you have about a 90% chance of still remembering it (the deck's desired retention, 90% by
default).</p>
"""

LICENCE = STYLE + f"""
<h2>Licence</h2>
<p>Vocab © {YEARS} {AUTHOR}.</p>
<p>Vocab is licensed under the <a href="https://creativecommons.org/licenses/by-nc/4.0/">Creative
Commons Attribution-NonCommercial 4.0 International licence (CC BY-NC 4.0)</a>, the licence of
the BHSA data it is built on. You may use, share and adapt Vocab freely, but <b>not
commercially</b>, and you must give appropriate credit to {AUTHOR} and to the ETCBC.</p>

<h2>Data</h2>
<p>BHSA (Biblia Hebraica Stuttgartensia Amstelodamensis), version 2021, by the Eep Talstra Centre
for Bible and Computer (ETCBC), Vrije Universiteit Amsterdam, licensed under CC BY-NC 4.0:
<a href="https://github.com/ETCBC/bhsa">github.com/ETCBC/bhsa</a>.</p>

<h2>Components</h2>
<table>
  <tr><th>Ezra SIL font, © SIL International</th>
      <td><a href="https://openfontlicense.org">SIL Open Font License 1.1</a></td></tr>
  <tr><th>py-fsrs and fsrs-rs-python (FSRS scheduling)</th><td>MIT</td></tr>
  <tr><th>Qt for Python (PySide6)</th>
      <td><a href="https://www.gnu.org/licenses/lgpl-3.0.html">LGPL v3</a></td></tr>
  <tr><th>Python</th><td>Python Software Foundation License</td></tr>
</table>
<p class="muted">Source code and releases:
<a href="https://github.com/ch-jensen/Vocab">github.com/ch-jensen/Vocab</a></p>
"""


def page(html: str) -> QTextBrowser:
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setHtml(html)
    view.setFrameShape(QTextBrowser.NoFrame)
    return view


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Vocab")
        self.resize(720, 640)

        icon = QLabel()
        png = APP_ROOT / "packaging" / "vocab-256.png"
        if png.exists():
            icon.setPixmap(QPixmap(str(png)).scaled(64, 64, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
        title = QLabel(f"<span style='font-size:20pt; font-weight:600;'>Vocab</span>"
                       f"<br><span style='color:#718096;'>Version {__version__} · "
                       f"© {YEARS} {AUTHOR}</span>")
        header = QHBoxLayout()
        header.addWidget(icon)
        header.addSpacing(8)
        header.addWidget(title, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(page(IDEA), "About")
        self.tabs.addTab(page(HOW), "How studying works")
        self.tabs.addTab(page(LICENCE), "Licence")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)
