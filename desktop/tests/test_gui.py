"""Smoke tests for the desktop UI (run without showing windows)."""

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

from vocab import decks                                    # noqa: E402
from vocab.decks import DeckConfig                         # noqa: E402
from vocab.store import DEFAULT_BHSA_DB, Store             # noqa: E402

pytestmark = pytest.mark.skipif(not DEFAULT_BHSA_DB.exists(), reason="run build_db.py first")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "user.sqlite") as s:
        yield s


def test_home_lists_decks(app, store):
    from vocab.gui.app import MainWindow
    decks.create_deck(store, "Frequency", DeckConfig(plan_id="hebrew-frequency"))
    win = MainWindow(store)
    assert win.home.table.rowCount() == 1
    assert win.home.table.item(0, 0).text() == "Frequency"
    assert win.home.table.item(0, 1).text() == "10"


def test_typed_study_flow(app, store):
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "Verbs", DeckConfig(pos=["verb"], rank_max=40, new_per_day=2))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    assert page.item.key.lex_id == "hbo:>MR["
    assert "<span" in page.clause.text()           # target word highlighted
    page.answer.setText("say")
    page._enter()                                  # submit
    assert "Correct" in page.feedback.text()
    assert page.controls.currentIndex() == 3
    page._enter()                                  # next
    assert page.item.key.lex_id != "hbo:>MR["
    page.answer.setText("xyz")
    page._enter()
    assert "✗" in page.feedback.text()
    assert store.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2


def test_self_graded_flow(app, store):
    from fsrs import Rating
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "Self", DeckConfig(plan_id="hebrew-frequency",
                                                       answer_mode="self", new_per_day=1))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    assert page.controls.currentIndex() == 1
    page.rate(Rating.Good)                          # ignored before the answer is shown
    assert store.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
    page._enter()                                   # show answer
    assert page.controls.currentIndex() == 2
    assert "min" in page.rate_buttons[Rating.Again].text()
    first = page.item
    page.rate(Rating.Good)
    assert store.con.execute("SELECT rating FROM reviews").fetchone()[0] == Rating.Good
    assert page.item is None or page.item is not first     # straight on, no Next step
    assert page.controls.currentIndex() != 3


def test_deck_editor_creates_deck(app, store):
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.custom_radio.setChecked(True)
    dlg.name.setText("Jonah")
    for i in range(dlg.books.count()):
        item = dlg.books.item(i)
        item.setCheckState(Qt.Checked if item.data(Qt.UserRole) == "Jona" else Qt.Unchecked)
    cfg = dlg.config()
    assert cfg.plan_id is None and cfg.passages[0].book == "Jona"
    assert cfg.passages[0].chapter_to == 4                # clamped to the book
    assert 0 < dlg.card_count() < 600
    dlg.save()
    saved = decks.get_deck(store, "Jonah")
    assert saved is not None and saved.config == cfg


def test_deck_editor_round_trip(app, store):
    from vocab.gui.deck_editor import DeckEditor
    # pos in the order the editor lists them
    cfg = DeckConfig(pos=["subs", "verb"], rank_min=10, rank_max=500, stems=["qal", "piel"],
                     tenses=["wayq"], suffix="without", split_stems=True, gloss_language="Danish",
                     new_per_day=15, answer_mode="self", show_lexeme=True)
    deck = decks.create_deck(store, "Mixed", cfg)
    assert DeckEditor(store, deck).config() == cfg


def test_return_key_shows_feedback(app, store):
    """A real Return key press in the answer box must show feedback, not skip ahead."""
    from PySide6.QtTest import QTest
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "Keys", DeckConfig(pos=["verb"], rank_max=40, new_per_day=2))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    first = page.item
    QTest.keyClicks(page.answer, "say")
    QTest.keyClick(page.answer, Qt.Key_Return)
    assert page.item is first                       # still on the same word
    assert page.controls.currentIndex() == 3
    assert "Correct" in page.feedback.text()
    QTest.keyClick(page.next_btn, Qt.Key_Return)    # Return again: next word
    assert page.item is not first
    assert page.feedback.text() == ""


def test_return_key_self_graded(app, store):
    from PySide6.QtTest import QTest
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "SelfKeys", DeckConfig(plan_id="hebrew-frequency",
                                                           answer_mode="self", new_per_day=2))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    first = page.item
    QTest.keyClick(page.show_btn, Qt.Key_Return)    # show answer
    assert page.controls.currentIndex() == 2 and page.item is first
    QTest.keyClick(page.rate_buttons[next(iter(page.rate_buttons))], Qt.Key_3)
    assert page.item is not first                   # rating goes straight to the next word
    assert page.controls.currentIndex() == 1 and page.feedback.text() == ""


def test_finished_for_now_screen(app, store):
    from fsrs import Rating
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "Done", DeckConfig(plan_id="hebrew-frequency",
                                                       answer_mode="self", new_per_day=1))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    page._enter()                       # show answer
    page.rate(Rating.Again)             # due again in 1 minute; nothing else is due
    assert page.item is None
    assert page.done.isVisibleTo(page)
    assert "Finished for now" in page.done_title.text()
    assert "1 word" in page.done_text.text()
    assert not page.continue_btn.isEnabled()
    assert page.wait_timer.isActive()
    page._learning_due()                # what the timer does after a minute
    assert page.continue_btn.isEnabled()


def test_counts_bar_and_tooltips(app, store):
    from fsrs import Rating
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "Bar", DeckConfig(plan_id="hebrew-frequency",
                                                      answer_mode="self", new_per_day=3))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    page._enter()
    page.rate(Rating.Again)                         # wrong: returns in 1 minute
    bar = page.counts
    assert bar.learning.text() == "0 (1) learning"
    assert bar.new.text() == "2 new"
    assert "later today" in bar.learning.toolTip() and bar.due.toolTip()
    win.show_home()
    assert win.home.table.item(0, 2).text() == "0 (1)"
    assert win.home.table.horizontalHeaderItem(2).toolTip() == bar.learning.toolTip()
