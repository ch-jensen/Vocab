"""Main window and entry point of the desktop app.

    python -m vocab.gui                    # uses %APPDATA%\\Vocab\\user.sqlite
    python -m vocab.gui --user-db test.sqlite
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QFontDatabase, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
                               QStackedWidget)

from .. import __version__
from .. import glosses
from ..migrate import import_score_csv
from ..store import APP_ROOT, Store
from .home import HomePage
from .stats_page import StatsPage
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
QLineEdit#chapters { padding: 0px 6px; font-size: 11pt; border-radius: 3px; }
QPushButton { padding: 7px 16px; border: 1px solid #cbd5e0; border-radius: 6px; background: #ffffff; }
QPushButton:hover { border-color: #b7791f; }
QPushButton:focus { border: 2px solid #b7791f; }
QPushButton:disabled { color: #a0aec0; }
QPushButton:flat { border: none; background: transparent; }
QProgressBar { background: #e8e7e2; border: none; border-radius: 5px; }
QProgressBar::chunk { background: #2a78d6; border-radius: 5px; }
QFrame#tile { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; }
QLabel#tileValue { font-size: 20pt; font-weight: 600; }
QTableWidget { font-size: 12pt; selection-background-color: #fbe3b0; selection-color: #1a202c; }
"""


def configure(app: QApplication) -> None:
    app.setApplicationName("Vocab")
    app.setStyle("Fusion")
    # Bundled fonts (Ezra SIL), used when no better Hebrew font is installed.
    for font_file in sorted((APP_ROOT / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font_file))
    icon = APP_ROOT / "packaging" / "vocab.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
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
and <a href="https://github.com/open-spaced-repetition/fsrs-rs-python">fsrs-rs</a>
(MIT/BSD licences). <b>Interface:</b> Qt for Python (LGPL).
<b>Font:</b> Ezra SIL by SIL International
(<a href="https://openfontlicense.org">SIL Open Font License</a>).</p>"""


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
        self.stats = StatsPage(store)
        self.pages.addWidget(self.stats)
        self.stats.finished.connect(self.show_home)
        self.home.stats_requested.connect(self.show_stats)
        self.setCentralWidget(self.pages)

        self.home.study_requested.connect(self.start_study)
        self.study.finished.connect(self.show_home)

        file_menu = self.menuBar().addMenu("&File")
        imp = QAction("&Import scores from the notebook version…", self)
        imp.triggered.connect(self.import_scores)
        file_menu.addAction(imp)
        imp_deck = QAction("Import &deck…", self)
        imp_deck.triggered.connect(self.home.import_deck)
        file_menu.addAction(imp_deck)
        exp_deck = QAction("E&xport deck…", self)
        exp_deck.triggered.connect(self.home.export_deck)
        file_menu.addAction(exp_deck)
        file_menu.addSeparator()
        imp_gloss = QAction("Import &gloss file…", self)
        imp_gloss.triggered.connect(self.import_glosses)
        file_menu.addAction(imp_gloss)
        exp_gloss = QAction("&Export glosses…", self)
        exp_gloss.triggered.connect(self.export_glosses)
        file_menu.addAction(exp_gloss)
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

    def show_stats(self) -> None:
        self.stats.refresh()
        self.pages.setCurrentWidget(self.stats)

    def import_glosses(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import gloss file", "", "Gloss files (*_glosses.csv);;CSV files (*.csv)")
        if not path:
            return
        try:
            r = glosses.import_csv(self.store, path)
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Import glosses", f"Could not read the file: {exc}")
            return
        QMessageBox.information(
            self, "Import glosses",
            f"{r.glosses} {r.language} glosses imported"
            + (f"; {r.unknown} words were not found" if r.unknown else "")
            + f".\n\nChoose “{r.language}” as gloss language in a deck's Study settings.")
        self.home.refresh()

    def export_glosses(self) -> None:
        languages = self.store.gloss_languages()
        language, ok = QInputDialog.getItem(self, "Export glosses", "Gloss language:",
                                            languages, 0, False)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export glosses", f"{language}_glosses.csv",
                                              "CSV files (*.csv)")
        if path:
            n = glosses.export_csv(self.store, language, path)
            QMessageBox.information(self, "Export glosses", f"{n} words written to {path}.")

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
    ap.add_argument("deck_file", nargs="?",
                    help="a .vocabdeck file to import (e.g. when opened from Explorer)")
    ap.add_argument("--self-test", metavar="REPORT",
                    help="check that the app works (used after building the .exe) and exit")
    args, qt_args = ap.parse_known_args(argv)

    app = QApplication([sys.argv[0], *qt_args])
    configure(app)
    if args.self_test:
        return self_test(app, args.self_test, args.bhsa_db)
    try:
        store = Store(args.user_db, args.bhsa_db)
    except (FileNotFoundError, RuntimeError) as exc:
        QMessageBox.critical(None, "Vocab", str(exc))
        return 1
    window = MainWindow(store)
    window.show()
    if args.deck_file:
        QTimer.singleShot(0, lambda: window.home.import_deck_file(args.deck_file))
    code = app.exec()
    store.close()
    return code


def self_test(app: QApplication, report: str, bhsa_db: str | None) -> int:
    """Exercise the main parts without showing a window; write OK or the error to `report`.

    A windowed .exe has no console, so the result goes to a file.
    """
    import tempfile
    import traceback
    from pathlib import Path

    from .. import decks, optimize, stats
    from ..decks import DeckConfig
    lines = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "user.sqlite", bhsa_db)
            deck = decks.create_deck(store, "Test", DeckConfig(plan_id="hebrew-frequency"))
            window = MainWindow(store)
            window.start_study(deck)
            item = window.study.item
            assert item is not None and item.key.lex_id == "hbo:W", item
            window.study.answer.setText("and")
            window.study._enter()
            assert "Correct" in window.study.feedback.text()
            window.show_stats()
            lines.append(f"coverage {stats.coverage(store):.4f}")
            lines.append(f"optimizer {optimize.fit(optimize.training_data(store), None).message}")
            families = QFontDatabase.families()
            lines.append("fonts " + ", ".join(f for f in ("SBL Hebrew", "Ezra SIL") if f in families))
            assert "Ezra SIL" in families, "bundled font not loaded"
            lines.append(f"bhsa {store.bhsa_db}")
            window.close()
            store.close()
        lines.insert(0, "OK")
        code = 0
    except Exception:
        lines.insert(0, "FAILED")
        lines.append(traceback.format_exc())
        code = 1
    Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
