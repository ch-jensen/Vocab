"""Smoke tests for the desktop UI (run without showing windows)."""

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

from vocab import decks                                    # noqa: E402
from vocab.decks import DeckConfig, Passage                # noqa: E402
from vocab.store import DEFAULT_BHSA_DB, Store             # noqa: E402

pytestmark = pytest.mark.skipif(not DEFAULT_BHSA_DB.exists(), reason="run build_db.py first")


@pytest.fixture(scope="module")
def app():
    from vocab.gui.app import VocabApplication
    return QApplication.instance() or VocabApplication([])


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "user.sqlite") as s:
        yield s


def test_home_lists_decks(app, store):
    from vocab.gui.app import MainWindow
    decks.create_deck(store, "Frequency", DeckConfig(plan_id="hebrew-frequency"))
    win = MainWindow(store)
    assert len(win.home.cards) == 1
    card = win.home.cards[0]
    assert card.name.text() == "Frequency" and card.language == "Hebrew"
    assert card.figures["new"].text() == "10"


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
    dlg.books.set_all(False)
    dlg.books.set_book("Jona")
    cfg = dlg.config()
    assert cfg.plan_id is None
    assert [(p.book, p.chapter_from, p.chapter_to) for p in cfg.passages] == [("Jona", None, None)]
    assert 0 < dlg.card_count() < 600
    dlg.save()
    saved = decks.get_deck(store, "Jonah")
    assert saved is not None and saved.config == cfg


def test_deck_editor_chapters_per_book(app, store):
    from vocab.decks import Passage
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.custom_radio.setChecked(True)
    dlg.name.setText("Primeval history and Exodus")
    dlg.books.set_all(False)
    dlg.books.set_book("Genesis", "1-11; 37–50")
    dlg.books.set_book("Exodus", "1-15")
    dlg.books.set_book("Jona")                      # whole book
    cfg = dlg.config()
    assert cfg.passages == [Passage("Genesis", 1, 11), Passage("Genesis", 37, 50),
                            Passage("Exodus", 1, 15), Passage("Jona")]
    n = dlg.card_count()
    dlg.save()
    # Reopening shows the same chapters per book.
    again = DeckEditor(store, decks.get_deck(store, "Primeval history and Exodus"))
    texts = {again.books._books[r][0]: again.books.edits[r].text()
             for r in range(len(again.books.edits))
             if again.books.table.item(r, 0).checkState() == Qt.Checked}
    assert texts == {"Genesis": "1–11; 37–50", "Exodus": "1–15", "Jona": ""}
    assert again.config() == cfg and again.card_count() == n


def test_deck_editor_bad_chapters(app, store):
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.custom_radio.setChecked(True)
    dlg.books.set_all(False)
    dlg.books.set_book("Jona", "3-9")               # Jonah has 4 chapters
    with pytest.raises(ValueError, match="Jonah"):
        dlg.config()
    dlg.update_count()
    assert "chapters 1–4" in dlg.count.text()
    dlg.books.set_all(False)
    with pytest.raises(ValueError, match="at least one book"):
        dlg.config()


def test_deck_editor_all_books_means_no_restriction(app, store):
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    assert dlg.config().passages is None
    dlg.books.set_book("Genesis", "1-50")           # all chapters: still the whole Bible
    assert dlg.config().passages is None


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
    assert bar.learning.text() == "0 (+1) learning"
    assert bar.new.text() == "2 new"
    assert "later today" in bar.learning.toolTip() and bar.due.toolTip()
    win.show_home()
    assert win.home.cards[0].figures["learning"].text() == "0 (+1)"
    assert win.home.cards[0].figures["learning"].toolTip() == bar.learning.toolTip()


def test_stats_page(app, store):
    from fsrs import Rating
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "S", DeckConfig(plan_id="hebrew-frequency", new_per_day=2))
    win = MainWindow(store)
    win.start_study(deck)
    win.study.session.rate(win.study.item, Rating.Easy)     # graduate 'and'
    win.show_stats()
    texts = " ".join(w.text() for w in win.stats.body.findChildren(type(win.study.feedback)))
    assert "0 mature words" in texts and "1 young words" in texts   # a new word just graduated
    assert "% " in texts or "%</span>" in texts           # coverage hero
    assert not win.stats.scheduling.fit_btn.isEnabled()      # too few reviews to fit
    assert "Default FSRS parameters" in win.stats.scheduling.fit_status.text()


def test_gloss_dialog_from_study(app, store):
    from vocab.gui.app import MainWindow
    from vocab.gui.gloss_dialog import GlossDialog
    deck = decks.create_deck(store, "G", DeckConfig(pos=["verb"], rank_max=40, new_per_day=1))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    page.answer.setText("speak")
    page._enter()
    assert "✗" in page.feedback.text()
    assert "edit-gloss" in page.facts.text()
    dlg = GlossDialog(store, "hbo:>MR[", "English")
    assert dlg.fields["default"].placeholderText() == "say"
    assert "qal" in dlg.fields
    dlg.fields["default"].setText("say, speak")
    dlg.save()
    assert store.glosses("hbo:>MR[", "English")["default"] == "say, speak"
    # Saving the built-in text again removes the user's own entry.
    dlg2 = GlossDialog(store, "hbo:>MR[", "English")
    assert dlg2.fields["default"].text() == "say, speak"
    dlg2.fields["default"].setText("say")
    dlg2.save()
    assert store.con.execute("SELECT COUNT(*) FROM user_glosses").fetchone()[0] == 0


def test_bar_chart_scale():
    from vocab.gui.charts import nice_max
    assert [nice_max(v) for v in (0, 1, 3, 7, 12, 180, 999)] == [1, 1, 5, 10, 20, 200, 1000]


def test_export_and_import_deck_from_home(app, store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from vocab.gui.app import MainWindow
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    decks.create_deck(store, "Jonah", DeckConfig(passages=[Passage("Jona", 1, 2)]))
    win = MainWindow(store)
    path = tmp_path / "jonah.vocabdeck"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    win.home.export_deck()
    assert path.exists() and "progress is not included" in shown[-1]
    result = win.home.import_deck_file(str(path))
    assert result.deck.name == "Jonah (2)"
    assert len(win.home.cards) == 2
    assert win.home.selected_deck().name == "Jonah (2)"
    bad = tmp_path / "bad.vocabdeck"
    bad.write_text("{}", encoding="utf-8")
    assert win.home.import_deck_file(str(bad)) is None and "not a Vocab deck" in shown[-1]


def test_deck_editor_semicolon_example(app, store):
    from vocab.decks import Passage
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.custom_radio.setChecked(True)
    dlg.books.set_all(False)
    dlg.books.set_book("Genesis", "1-3; 11; 45-48")
    assert dlg.config().passages == [Passage("Genesis", 1, 3), Passage("Genesis", 11, 11),
                                     Passage("Genesis", 45, 48)]
    assert dlg.card_count() > 0


def test_deck_file_opened_from_finder(app, store, tmp_path, monkeypatch):
    """macOS delivers double-clicked files as FileOpen events, also before the window exists."""
    from PySide6.QtGui import QFileOpenEvent
    from vocab.gui.app import MainWindow, VocabApplication
    if not isinstance(app, VocabApplication):
        pytest.skip("another QApplication was created first")
    opened = []
    win = MainWindow(store)
    monkeypatch.setattr(win.home, "import_deck_file", lambda path: opened.append(path))
    app.window, app.pending = None, []
    path = str(tmp_path / "shared.vocabdeck")
    assert app.event(QFileOpenEvent(path))           # before the window: queued
    assert app.event(QFileOpenEvent(str(tmp_path / "notes.txt")))   # other files: ignored
    assert app.pending == [path] and opened == []
    app.set_window(win)
    app.processEvents()
    assert opened == [path] and app.pending == []
    app.window = None


def test_deck_editor_counts_in_background(app, store):
    """The word count runs on a worker thread; only the newest result is shown."""
    import time
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.custom_radio.setChecked(True)
    dlg.books.set_all(False)
    dlg.books.set_book("Genesis", "1-3")
    dlg.update_count()
    first = dlg._generation
    dlg.books.set_book("Jona")
    dlg.update_count()                                  # supersedes the first count
    assert dlg.count.text() == "Counting words…"
    expected = dlg.card_count()
    deadline = time.time() + 30
    while "words in this deck" not in dlg.count.text() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert dlg.count.text() == f"{expected} words in this deck"
    dlg._count_done(first, 1)                            # a stale result is ignored
    assert dlg.count.text() == f"{expected} words in this deck"


def test_about_window(app):
    from vocab import __version__
    from vocab.gui.about import AboutDialog
    dlg = AboutDialog()
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == \
        ["About", "How studying works", "Licence"]
    text = [dlg.tabs.widget(i).toPlainText() for i in range(dlg.tabs.count())]
    assert "flash card approach" in text[0] and "such as Anki" in text[0] and "BHSA" in text[0]
    assert "Again" in text[1] and "your usual time" in text[1] and "21 days" in text[1]
    assert "Christian Canu Højgaard" in text[2] and "CC BY-NC 4.0" in text[2]
    assert "ETCBC" in text[2]


def test_current_group_underlined(app, store):
    from fsrs import Rating
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "U", DeckConfig(plan_id="hebrew-frequency",
                                                    answer_mode="self", new_per_day=1))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    assert page.counts.current() == "new"
    assert page.counts.new.font().underline() and not page.counts.due.font().underline()
    page._enter()
    page.rate(Rating.Again)                     # nothing else due: finished for now
    assert page.item is None and page.counts.current() is None
    from datetime import datetime, timedelta, timezone
    page.session.clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=2)
    page.next_card()
    assert page.item is not None and page.counts.current() == "learning"


def test_overview_tiles_on_deck_list(app, store):
    from fsrs import Rating
    from PySide6.QtWidgets import QLabel
    from vocab.gui.app import MainWindow
    deck = decks.create_deck(store, "O", DeckConfig(plan_id="hebrew-frequency", new_per_day=2))
    win = MainWindow(store)

    def texts():
        return " ".join(l.text() for l in win.home.overview.findChildren(QLabel))
    assert "mature words" in texts() and "0 reviews today" in texts()
    assert "0" in texts() and "reviews today" in texts() and "study streak" in texts()
    win.start_study(deck)
    win.study.session.rate(win.study.item, Rating.Easy)     # one review, one learned word
    win.show_home()                                          # back on the deck list: refreshed
    labels = [l.text() for l in win.home.overview.findChildren(QLabel)]
    assert labels[labels.index("reviews today") - 1] == "1"
    assert labels[labels.index("young words") - 1] == "1"
    assert len(win.home.findChildren(type(win.home.overview), "overview")) == 1   # no duplicates


def test_deck_editor_greek(app, store):
    from vocab.gui.deck_editor import DeckEditor
    dlg = DeckEditor(store, None)
    dlg.corpus.setCurrentIndex(dlg.corpus.findData("n1904"))
    assert dlg.plan.currentData() == "greek-frequency"
    assert dlg.voices.count() > 0 and dlg.moods.count() > 0 and dlg.stems.count() == 0
    assert dlg.books._books[0][1] == "Matthew"
    assert "Swahili" in [dlg.gloss.itemText(i) for i in range(dlg.gloss.count())]
    dlg.gloss.setCurrentText("Danish")
    dlg.name.setText("NT Greek")
    cfg = dlg.config()
    assert (cfg.corpus, cfg.plan_id, cfg.languages, cfg.gloss_language) == \
        ("n1904", "greek-frequency", ["Greek"], "Danish")
    dlg.save()
    saved = decks.get_deck(store, "NT Greek")
    again = DeckEditor(store, saved)
    assert again.config() == saved.config and not again.corpus.isEnabled()


def test_study_greek_left_to_right(app, store):
    from vocab.gui.app import MainWindow
    from vocab.gui.study import clause_html
    deck = decks.create_deck(store, "G", DeckConfig(corpus="n1904", plan_id="greek-frequency",
                                                    languages=["Greek"], answer_mode="self"))
    win = MainWindow(store)
    win.start_study(deck)
    page = win.study
    assert 'dir="ltr"' in clause_html(page.item)
    assert "Greek" in page.clause.font().families()[0] or "SBL Greek" in page.clause.font().families()
    page._enter()                                       # show answer and facts
    assert "New Testament" in page.facts.text()


def test_stats_overview_and_details(app, store):
    from fsrs import Rating
    from PySide6.QtWidgets import QLabel
    from vocab.gui.app import MainWindow
    greek = decks.create_deck(store, "NT", DeckConfig(corpus="n1904", plan_id="greek-frequency",
                                                      languages=["Greek"], new_per_day=2))
    win = MainWindow(store)
    win.start_study(greek)
    win.study.session.rate(win.study.item, Rating.Easy)         # ὁ learned
    win.show_stats()
    cards = {c.corpus: c for c in win.stats.cards}
    assert set(cards) == {"bhsa", "n1904"}
    hebrew_text = " ".join(l.text() for l in cards["bhsa"].findChildren(QLabel))
    assert "Not started yet" in hebrew_text
    greek_text = " ".join(l.text() for l in cards["n1904"].findChildren(QLabel))
    assert "of the text learned" in greek_text and "1 word learned" in greek_text and "1 deck" in greek_text
    # The overview has no per-book table; the details do.
    assert "Genesis" not in " ".join(l.text() for l in win.stats.body.findChildren(QLabel))
    cards["n1904"].details.click()
    assert win.pages.currentWidget() is win.corpus_stats
    assert win.corpus_stats.title.text() == "Greek New Testament (Nestle 1904)"
    from PySide6.QtWidgets import QTableWidget
    tables = win.corpus_stats.body.findChildren(QTableWidget)
    assert tables[0].item(0, 0).text() == "Matthew" and tables[0].rowCount() == 27
    assert tables[1].item(0, 0).text() == "NT"                   # only this text's decks
    win.corpus_stats.finished.emit()                              # ← Statistics
    assert win.pages.currentWidget() is win.stats


def test_stats_per_corpus_engine(store):
    from datetime import datetime, timezone
    from vocab import stats
    for lex in ("grc:καί", "hbo:W"):
        store.con.execute("INSERT INTO cards (lex_id, stem, state, due, last_review, created_at) "
                          "VALUES (?, '*', 2, '2030-01-01T04:00:00.000+00:00', "
                          "'2029-12-01T04:00:00.000+00:00', '2026-01-01T00:00:00.000+00:00')", (lex,))
    store.con.commit()
    now = datetime(2029, 12, 15, tzinfo=timezone.utc)
    assert stats.summary(store, now).learned == 2
    assert stats.summary(store, now, corpus="n1904").learned == 1
    assert stats.summary(store, now, corpus="n1904").mature == 1          # 31-day interval
    assert sum(n for _, n in stats.forecast(store, 30, now, corpus="bhsa")) == 1


def test_deck_cards_select_and_study(app, store):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from vocab.gui.app import MainWindow
    decks.create_deck(store, "A Hebrew", DeckConfig(plan_id="hebrew-frequency"))
    decks.create_deck(store, "B Greek", DeckConfig(corpus="n1904", plan_id="greek-frequency",
                                                   languages=["Greek"]))
    win = MainWindow(store)
    home = win.home
    assert [c.deck.name for c in home.cards] == ["A Hebrew", "B Greek"]
    assert [c.language for c in home.cards] == ["Hebrew", "Greek"]
    assert home.selected_deck().name == "A Hebrew" and home.cards[0].property("selected")
    QTest.mouseClick(home.cards[1], Qt.LeftButton)              # click a card: selects it
    assert home.selected_deck().name == "B Greek"
    assert home.cards[1].property("selected") and not home.cards[0].property("selected")
    QTest.keyClick(home, Qt.Key_Up)                              # arrow keys move the selection
    assert home.selected_deck().name == "A Hebrew"
    home.cards[1].study_btn.click()                              # Study › on a card studies that deck
    assert win.pages.currentWidget() is win.study and win.study.deck_label.text() == "B Greek"
    win.show_home()
    QTest.keyClick(home, Qt.Key_Return)                          # Enter studies the selected deck
    assert win.study.deck_label.text() == "A Hebrew"
