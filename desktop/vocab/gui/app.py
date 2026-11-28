"""Main window and entry point of the desktop app.

    python -m vocab.gui                    # progress in the user data folder (store.user_data_dir)
    python -m vocab.gui --user-db test.sqlite
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QEvent, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QAction, QFontDatabase, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
                               QStackedWidget)

from .. import __version__
from .. import glosses
from ..migrate import import_score_csv
from ..store import APP_ROOT, Store
from .about import AboutDialog
from .home import HomePage
from .stats_page import CorpusStatsPage, StatsPage
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
QFrame#deckCard { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }
QFrame#deckCard:hover { border-color: #d6b37a; }
QFrame#deckCard[selected="true"] { border: 2px solid #b7791f; background: #fffaf0; }
QLabel#deckName { font-size: 13.5pt; font-weight: 600; }
QLabel#deckFigure { font-size: 15pt; font-weight: 600; }
QPushButton#primary { background: #b7791f; color: #ffffff; border: 1px solid #b7791f; font-weight: 600; }
QPushButton#primary:hover { background: #9c6519; }
QPushButton#primary:disabled { background: #ead9bd; border-color: #ead9bd; color: #ffffff; }
QFrame#tileCompact { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; }
QLabel#tileValueCompact { font-size: 12pt; font-weight: 600; }
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
        self.corpus_stats = CorpusStatsPage(store)
        self.pages.addWidget(self.corpus_stats)
        self.stats.details_requested.connect(self.show_corpus_stats)
        self.corpus_stats.finished.connect(self.show_stats)
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
        about.setMenuRole(QAction.AboutRole)          # macOS: in the application menu
        about.triggered.connect(lambda: AboutDialog(self).exec())
        help_menu.addAction(about)

        self.show_home()

    def show_home(self) -> None:
        self.home.refresh()
        self.pages.setCurrentWidget(self.home)

    def show_corpus_stats(self, corpus: str) -> None:
        self.corpus_stats.show_corpus(corpus)
        self.pages.setCurrentWidget(self.corpus_stats)

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


class _Prewarm(QRunnable):
    """After start-up, do the one-time counts in the background (read-only connection),
    so the statistics and new decks are quick when first opened."""

    def __init__(self, store: Store):
        super().__init__()
        self.store = store

    def run(self) -> None:
        from .. import decks as decks_mod, stats as stats_mod
        try:
            con = self.store.read_only_connection()
            try:
                decks_mod._askable_stems(con)
                stats_mod.word_counts(con)
            finally:
                con.close()
        except Exception:     # only a speed-up; the app computes these itself if needed
            pass


class VocabApplication(QApplication):
    """QApplication that also receives files opened from the Finder on macOS.

    On Windows a double-clicked .vocabdeck file arrives as a command-line
    argument; on macOS it arrives as a QFileOpenEvent, also while the app is
    already running.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self.window: MainWindow | None = None
        self.pending: list[str] = []

    def event(self, event) -> bool:
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if path.lower().endswith(".vocabdeck"):
                self.open_deck_file(path)
            return True
        return super().event(event)

    def open_deck_file(self, path: str) -> None:
        if self.window is None:
            self.pending.append(path)          # imported once the window exists
        else:
            QTimer.singleShot(0, lambda: self.window.home.import_deck_file(path))

    def set_window(self, window: "MainWindow") -> None:
        self.window = window
        for path in self.pending:
            self.open_deck_file(path)
        self.pending.clear()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vocab")
    ap.add_argument("--user-db")
    ap.add_argument("--bhsa-db")
    ap.add_argument("deck_file", nargs="?",
                    help="a .vocabdeck file to import (e.g. when opened from Explorer)")
    ap.add_argument("--self-test", metavar="REPORT",
                    help="check that the app works (used after building the app) and exit")
    args, qt_args = ap.parse_known_args(argv)

    app = VocabApplication([sys.argv[0], *qt_args])
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
    QThreadPool.globalInstance().start(_Prewarm(store))
    if args.deck_file and args.deck_file.lower().endswith(".vocabdeck"):
        app.open_deck_file(args.deck_file)
    app.set_window(window)
    code = app.exec()
    store.close()
    return code


def self_test(app: QApplication, report: str, bhsa_db: str | None) -> int:
    """Exercise the main parts without showing a window; write OK or the error to `report`.

    A windowed app has no console, so the result goes to a file.
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
            greek = decks.create_deck(store, "Greek", DeckConfig(
                corpus="n1904", plan_id="greek-frequency", languages=["Greek"]))
            window.start_study(greek)
            assert window.study.item.key.lex_id == "grc:ὁ", window.study.item
            window.study.answer.setText("the")
            window.study._enter()
            assert "Correct" in window.study.feedback.text()
            lines.append("greek " + window.study.item.clause[0].form)
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
