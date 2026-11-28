"""Statistics, FSRS fitting and the user's glosses."""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest
from fsrs import Rating, State

from vocab import decks, glosses, optimize, stats
from vocab.decks import CardKey, DeckConfig
from vocab.session import StudySession
from vocab.store import DEFAULT_BHSA_DB, Store, ts

pytestmark = pytest.mark.skipif(not DEFAULT_BHSA_DB.exists(), reason="run build_db.py first")
UTC = timezone.utc
NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "user.sqlite") as s:
        yield s


def add_card(store, lex_id, state, due, stem="*"):
    cur = store.con.execute(
        "INSERT INTO cards (lex_id, stem, state, step, stability, difficulty, due, last_review, created_at) "
        "VALUES (?, ?, ?, NULL, 5, 5, ?, ?, ?)", (lex_id, stem, int(state), ts(due), ts(NOW), ts(NOW)))
    return cur.lastrowid


def add_review(store, card_id, at, rating, state_before):
    store.con.execute(
        "INSERT INTO reviews (card_id, deck_id, node, reviewed_at, rating, duration_ms, mode, "
        "state_before) VALUES (?, NULL, NULL, ?, ?, 3000, 'self', ?)",
        (card_id, ts(at), int(rating), state_before))


# --- statistics ----------------------------------------------------------------

def test_summary_and_streak(store):
    c = add_card(store, "hbo:W", State.Review, NOW + timedelta(days=3))
    add_card(store, "hbo:H", State.Learning, NOW)
    for days_ago in (0, 1, 2, 4):
        add_review(store, c, NOW - timedelta(days=days_ago), Rating.Good, 2)
    add_review(store, c, NOW - timedelta(days=1, hours=1), Rating.Again, 2)
    s = stats.summary(store, NOW, UTC)
    assert (s.learned, s.learning, s.reviews_total, s.reviews_today) == (1, 1, 5, 1)
    assert s.streak_days == 3                      # today, yesterday, the day before
    assert s.retention_30d == pytest.approx(4 / 5)


def test_reviews_per_day_and_forecast(store):
    c = add_card(store, "hbo:W", State.Review, NOW - timedelta(days=2))    # overdue: today
    add_card(store, "hbo:H", State.Review, NOW + timedelta(days=5))
    add_review(store, c, NOW - timedelta(days=3), Rating.Good, 0)
    add_review(store, c, NOW, Rating.Good, 2)
    per_day = stats.reviews_per_day(store, 7, NOW, UTC)
    assert len(per_day) == 7 and per_day[-1][1] == 1 and per_day[-4][1] == 1
    fc = stats.forecast(store, 10, NOW, UTC)
    assert fc[0][1] == 1 and fc[5][1] == 1 and sum(n for _, n in fc) == 2


def test_study_day_rollover():
    assert stats.study_day(datetime(2026, 3, 2, 3, tzinfo=UTC), UTC).day == 1
    assert stats.study_day(datetime(2026, 3, 2, 5, tzinfo=UTC), UTC).day == 2


def test_coverage(store):
    assert stats.coverage(store) == 0
    add_card(store, "hbo:W", State.Review, NOW)                 # 'and': about 12% of all words
    cov = stats.coverage(store)
    assert 0.10 < cov < 0.13
    add_card(store, "hbo:H", State.Learning, NOW)               # learning does not count
    assert stats.coverage(store) == cov
    books = stats.coverage_by_book(store, corpus="bhsa")
    assert len(books) == 39 and books[0].book == "Genesis" and 0 < books[0].share < 1
    greek = stats.coverage_by_book(store, corpus="n1904")
    assert len(greek) == 27 and greek[0].book == "Matthew" and greek[0].known == 0
    assert len(stats.coverage_by_book(store)) == 66
    assert stats.coverage(store, "n1904") == 0


def test_coverage_per_stem(store):
    add_card(store, "hbo:HLK[", State.Review, NOW, stem="qal")
    known = store.con.execute("SELECT COUNT(*) FROM bhsa.words WHERE lex_id='hbo:HLK[' "
                              "AND stem='qal'").fetchone()[0]
    total = store.con.execute("SELECT COUNT(*) FROM bhsa.words w JOIN bhsa.lexemes l USING (lex_id) "
                              "WHERE l.corpus = 'bhsa'").fetchone()[0]
    assert stats.coverage(store) == pytest.approx(known / total)


def test_deck_progress(store):
    deck = decks.create_deck(store, "d", DeckConfig(pos=["verb"], rank_max=50))
    add_card(store, "hbo:>MR[", State.Review, NOW)
    add_card(store, "hbo:HJH[", State.Learning, NOW)
    p = stats.deck_progress(store, deck)
    assert (p.learned, p.learning) == (1, 1) and p.total > 2


# --- FSRS fitting ----------------------------------------------------------------

def synthetic_history(store, n_cards=220, seed=3):
    """Words reviewed at growing intervals; forgetting is likelier after long gaps."""
    rng = random.Random(seed)
    lex_ids = [r[0] for r in store.con.execute(
        "SELECT lex_id FROM bhsa.lexemes WHERE language='Hebrew' ORDER BY rank LIMIT ?", (n_cards,))]
    start = NOW - timedelta(days=120)
    for lex_id in lex_ids:
        card = add_card(store, lex_id, State.Review, NOW)
        at, interval, state = start + timedelta(hours=rng.randint(0, 200)), 1.0, 0
        add_review(store, card, at, Rating.Good, state)
        state = 2
        for _ in range(6):
            at += timedelta(days=interval)
            if at > NOW:
                break
            forgot = rng.random() < 1 - 0.9 ** (interval / (3 + 2 * _))
            add_review(store, card, at, Rating.Again if forgot else Rating.Good, state)
            interval = 1 if forgot else interval * 2.5
    store.con.commit()


def test_too_few_reviews(store):
    data = optimize.training_data(store, UTC)
    result = optimize.fit(data, None)
    assert not result.applied and "400" in result.message


def test_fit_and_apply(store):
    synthetic_history(store)
    data = optimize.training_data(store, UTC)
    assert data.reviews >= optimize.MIN_REVIEWS and len(data.items) > 100
    result = optimize.fit(data, None)
    assert len(result.parameters) == 21
    assert result.loss_after <= result.loss_before or not result.applied
    optimize.apply(store, result, NOW)
    if result.applied:
        assert json.loads(store.get_meta("fsrs_parameters")) == result.parameters
        assert "Fitted" in optimize.status(store)
        # A session picks the fitted parameters up.
        deck = decks.create_deck(store, "d", DeckConfig(plan_id="hebrew-frequency"))
        assert list(StudySession(store, deck).scheduler.parameters) == result.parameters
    optimize.reset(store)
    assert "Default" in optimize.status(store)


def test_imported_cards_left_out_of_training(store):
    card = add_card(store, "hbo:W", State.Review, NOW)
    add_review(store, card, NOW - timedelta(days=5), Rating.Good, 2)    # first review: not new
    add_review(store, card, NOW, Rating.Good, 2)
    assert optimize.training_data(store, UTC).items == []


# --- glosses -------------------------------------------------------------------

def test_set_gloss_overrides_and_resets(store):
    assert store.glosses("hbo:>MR[", "English")["default"] == "say"
    glosses.set_gloss(store, "hbo:>MR[", "English", "default", "say, speak")
    assert store.glosses("hbo:>MR[", "English")["default"] == "say, speak"
    glosses.set_gloss(store, "hbo:>MR[", "English", "default", "")
    assert store.glosses("hbo:>MR[", "English")["default"] == "say"


def test_import_and_export_gloss_file(store, tmp_path):
    f = tmp_path / "German_glosses.csv"
    f.write_text(",lex,default,qal,piel\n0,>MR[,sagen,,\n1,DBR[,,,reden\n2,XXX/,nichts,,\n",
                 encoding="utf-8")
    r = glosses.import_csv(store, f)
    # >MR[ is both Hebrew and Aramaic, so it gets the gloss twice.
    assert (r.language, r.glosses, r.unknown) == ("German", 3, 1)
    assert "German" in store.gloss_languages()
    assert store.glosses("hbo:DBR[", "German") == {"piel": "reden"}
    # A German deck only has words with German glosses.
    assert {k.lex_id for k in decks.deck_cards(store.con, DeckConfig(gloss_language="German"))} \
        == {"hbo:>MR[", "hbo:DBR["}
    out = tmp_path / "out.csv"
    assert glosses.export_csv(store, "German", out) == 2
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",lex,default,piel" and ">MR[,sagen," in text


def test_export_includes_builtin(store, tmp_path):
    glosses.set_gloss(store, "hbo:>B/", "Danish", "default", "fader")
    out = tmp_path / "Danish_glosses.csv"
    n = glosses.export_csv(store, "Danish", out)
    assert n > 1500 and ">B/,fader" in out.read_text(encoding="utf-8")


def test_young_and_mature(store):
    # 'and' was last reviewed 30 days ago and is due in 5 days: interval 35 days -> mature.
    c1 = add_card(store, "hbo:W", State.Review, NOW + timedelta(days=5))
    store.con.execute("UPDATE cards SET last_review = ? WHERE card_id = ?",
                      (ts(NOW - timedelta(days=30)), c1))
    # 'the': interval 4 days -> young.
    c2 = add_card(store, "hbo:H", State.Review, NOW + timedelta(days=3))
    store.con.execute("UPDATE cards SET last_review = ? WHERE card_id = ?",
                      (ts(NOW - timedelta(days=1)), c2))
    # Reviews: c1 remembered after 25 days (mature), c2 forgotten after 2 days (young),
    # c2 remembered after 1 day (young).
    add_review(store, c1, NOW - timedelta(days=55), Rating.Good, 0)
    add_review(store, c1, NOW - timedelta(days=30), Rating.Good, 2)
    add_review(store, c2, NOW - timedelta(days=4), Rating.Good, 0)
    add_review(store, c2, NOW - timedelta(days=2), Rating.Again, 2)
    add_review(store, c2, NOW - timedelta(days=1), Rating.Good, 2)
    store.con.commit()
    s = stats.summary(store, NOW, UTC)
    assert (s.learned, s.young, s.mature) == (2, 1, 1)
    assert s.retention_mature == 1.0 and s.retention_young == 0.5
    assert s.retention_30d == pytest.approx(2 / 3)
    cov = stats.coverage_detail(store, tz=UTC)
    and_words = store.con.execute("SELECT COUNT(*) FROM bhsa.words WHERE lex_id='hbo:W'").fetchone()[0]
    the_words = store.con.execute("SELECT COUNT(*) FROM bhsa.words WHERE lex_id='hbo:H'").fetchone()[0]
    assert (cov.known, cov.mature) == (and_words + the_words, and_words)
    books = stats.coverage_by_book(store, UTC, corpus="bhsa")
    assert sum(b.mature for b in books) == and_words
    deck = decks.create_deck(store, "d", DeckConfig(plan_id="hebrew-frequency"))
    p = stats.deck_progress(store, deck, UTC)
    assert (p.learned, p.mature, p.young) == (2, 1, 1)
    assert stats.interval_days(None, ts(NOW)) == 0
