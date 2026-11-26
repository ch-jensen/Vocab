"""Main window and entry point of the desktop app.

    python -m vocab.gui                    # uses %APPDATA%\\Vocab\\user.sqlite
    python -m vocab.gui --user-db test.sqlite
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow, QMessageBox,
                               QStackedWidget)

from .. import __version__
from ..migrate import import_score_csv
from ..store import Store
from .home import HomePage
from .study import StudyPage

# The base font size is set with QApplication.setFont, not here: a font size in
# the style sheet would override the large Hebrew fonts set on labels.
STYLE = """
QLabel#title { font-size: 20pt; font-weight: 600; }
QLabel#subtitle { font-size: 14pt; font-weight: 600; }
QLabel#muted { color: #718096; }
QFrame#rule { color: #e2e8f0; }
QLineEdit { padding: 8px; font-size: 14pt; border: 1px solid #cbd5e0; border-radius: 6px; }
QLineEdit:focus { border-color: #b7791f; }
QPushButton { padding: 7px 16px; border: 1px solid #cbd5e0; border-radius: 6px; background: #ffffff; }
QPushButton:hover { border-color: #b7791f; }
QPushButton:focus { border: 2px solid #b7791f; }
QPushButton:disabled { color: #a0aec0; }
QPushButton:flat { border: none; background: transparent; }
QTableWidget { font-size: 12pt; selection-background-color: #fbe3b0; selection-color: #1a202c; }
"""


def configure(app: QApplication) -> None:
    app.setApplicationName("Vocab")
    app.setStyle("Fusion")
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(STYLE)

ABOUT = f"""<h3>Vocab {__version__}</h3>
<p>Vocabulary training for Biblical Hebrew and Aramaic with attested forms
and FSRS scheduling.</p>
<p><b>Data:</b> BHSA (Biblia Hebraica Stuttgartensia Amstelodamensis) by the
Eep Talstra Centre for Bible and Computer (ETCBC), licensed
<a href="https://creativecommons.org/licenses/by-nc/4.0/">CC BY-NC 4.0</a>.
<a href="https://github.com/ETCBC/bhsa">github.com/ETCBC/bhsa</a></p>
<p><b>Scheduling:</b> <a href="https://github.com/open-spaced-repetition/py-fsrs">py-fsrs</a>
(MIT licence). <b>Interface:</b> Qt for Python (LGPL).</p>"""


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setWindowTitle("Vocab: Biblical Hebrew")
        self.resize(1000, 700)

        self.home = HomePage(store)
        self.study = StudyPage(store)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.home)
        self.pages.addWidget(self.study)
        self.setCentralWidget(self.pages)

        self.home.study_requested.connect(self.start_study)
        self.study.finished.connect(self.show_home)

        file_menu = self.menuBar().addMenu("&File")
        imp = QAction("&Import scores from the notebook version…", self)
        imp.triggered.connect(self.import_scores)
        file_menu.addAction(imp)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About Vocab", self)
        about.triggered.connect(lambda: QMessageBox.about(self, "About Vocab", ABOUT))
        help_menu.addAction(about)

        self.show_home()

    def show_home(self) -> None:
        self.home.refresh()
        self.pages.setCurrentWidget(self.home)

    def start_study(self, deck) -> None:
        self.pages.setCurrentWidget(self.study)
        self.study.start(deck)

    def import_scores(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import score files", "", "Score files (*_score.csv);;CSV files (*.csv)")
        if not files:
            return
        lines = []
        for path in files:
            try:
                r = import_score_csv(self.store, path)
                lines.append(f"{path}: {r.imported} words imported, {r.skipped_existing} already "
                             f"present, {r.unknown} not found")
            except Exception as exc:   # a malformed file should not crash the app
                lines.append(f"{path}: could not be read ({exc})")
        QMessageBox.information(self, "Import", "\n".join(lines))
        self.home.refresh()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vocab")
    ap.add_argument("--user-db")
    ap.add_argument("--bhsa-db")
    args, qt_args = ap.parse_known_args(argv)

    app = QApplication([sys.argv[0], *qt_args])
    configure(app)
    try:
        store = Store(args.user_db, args.bhsa_db)
    except (FileNotFoundError, RuntimeError) as exc:
        QMessageBox.critical(None, "Vocab", str(exc))
        return 1
    window = MainWindow(store)
    window.show()
    code = app.exec()
    store.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
