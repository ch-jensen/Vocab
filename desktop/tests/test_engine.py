"""Engine tests against the real BHSA database (skipped if it is not built)."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from fsrs import Rating, State

from vocab import decks
from vocab.decks import ALL_STEMS, CardKey, DeckConfig, Passage
from vocab.migrate import import_score_csv
from vocab.occurrences import choose_occurrence, strip_accents
from vocab.session import StudySession, day_start, expected_gloss
from vocab.store import DEFAULT_BHSA_DB, Store

pytestmark = pytest.mark.skipif(not DEFAULT_BHSA_DB.exists(), reason="run build_db.py first")

UTC = timezone.utc


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "user.sqlite") as s:
        yield s


@pytest.fixture
def clock():
    return Clock(datetime(2026, 3, 2, 10, 0, tzinfo=UTC))


def session(store, cfg, clock, name="deck"):
    deck = decks.get_deck(store, name) or decks.create_deck(store, name, cfg)
    return StudySession(store, deck, clock=clock, tz=UTC, rng=random.Random(1), fuzzing=False)


# --- decks -------------------------------------------------------------------

def test_plan_deck_order(store):
    keys = decks.deck_cards(store.con, DeckConfig(plan_id="hebrew-frequency"))
    askable = store.con.execute(
        "SELECT COUNT(DISTINCT lex_id) FROM bhsa.words WHERE lex_id LIKE 'hbo:%' "
        "AND qere_utf8 IS NULL AND form_utf8 <> ''").fetchone()[0]
    assert len(keys) == askable and 8400 < askable < 8522
    assert keys[:3] == [CardKey("hbo:W", "*"), CardKey("hbo:H", "*"), CardKey("hbo:L", "*")]


def test_filter_deck(store):
    cfg = DeckConfig(pos=["verb"], rank_max=200)
    keys = decks.deck_cards(store.con, cfg)
    assert keys and all(store.lexeme(k.lex_id)["sp"] == "verb" for k in keys)
    assert keys[0] == CardKey("hbo:>MR[", "*")
    assert all(store.lexeme(k.lex_id)["rank"] <= 200 for k in keys)


def test_split_stems(store):
    cfg = DeckConfig(pos=["verb"], rank_max=100, split_stems=True)
    keys = decks.deck_cards(store.con, cfg)
    halak = [k.stem for k in keys if k.lex_id == "hbo:HLK["]
    assert halak[0] == "qal" and {"hit", "piel", "hif"} <= set(halak)


def test_stem_filter_only_affects_verbs(store):
    cfg = DeckConfig(rank_max=30, stems=["nif"])
    keys = {k.lex_id for k in decks.deck_cards(store.con, cfg)}
    assert "hbo:W" in keys            # not a verb: unaffected
    assert "hbo:>MR[" in keys         # has nifal forms
    assert "hbo:HJH[" in keys         # has nifal forms
    for node, _ in decks.occurrences(store.con, cfg, CardKey("hbo:>MR[", "*")):
        assert store.word(node)["stem"] == "nif"


def test_passage_and_suffix_filter(store):
    cfg = DeckConfig(passages=[Passage("Jona")], suffix="with")
    keys = decks.deck_cards(store.con, cfg)
    assert keys
    for node, _ in decks.occurrences(store.con, cfg, keys[0]):
        w = store.word(node)
        assert w["has_suffix"] == 1
        assert store.con.execute("SELECT book FROM bhsa.verses WHERE verse_id=?",
                                 (w["verse_id"],)).fetchone()[0] == "Jona"


def test_gloss_language_restricts_deck(store):
    danish = decks.deck_cards(store.con, DeckConfig(gloss_language="Danish"))
    english = decks.deck_cards(store.con, DeckConfig())
    assert 0 < len(danish) < len(english)


def test_include_exclude(store):
    cfg = DeckConfig(pos=["verb"], rank_max=10, include_lex=["hbo:MLK/"], exclude_lex=["hbo:>MR["])
    keys = {k.lex_id for k in decks.deck_cards(store.con, cfg)}
    assert "hbo:MLK/" in keys and "hbo:>MR[" not in keys


def test_deck_round_trip(store):
    cfg = DeckConfig(passages=[Passage("Genesis", 1, 11)], stems=["qal"])
    deck = decks.create_deck(store, "Gen", cfg)
    assert decks.get_deck(store, "Gen").config == cfg
    assert decks.get_deck(store, deck.deck_id).name == "Gen"


def test_invalid_config():
    with pytest.raises(ValueError):
        DeckConfig(suffix="sometimes").validate()


# --- occurrences ---------------------------------------------------------------

def test_strip_accents():
    assert strip_accents("אֱלֹהִ֑ים") == "אֱלֹהִים"


def test_choose_occurrence_prefers_unseen_forms():
    rng = random.Random(0)
    cands = [(1, "דָּבָר"), (2, "דָּבָר"), (3, "דְּבַר")]
    # Form of node 1 seen: must pick the other form.
    assert choose_occurrence(cands, {1: "2026-01-01"}, rng) == 3
    # Everything seen: pick the node shown longest ago.
    seen = {1: "2026-01-03", 2: "2026-01-01", 3: "2026-01-02"}
    picks = {choose_occurrence(cands, seen, random.Random(i)) for i in range(20)}
    assert picks <= {2, 3}


# --- glosses -----------------------------------------------------------------

def test_expected_gloss():
    g = {"default": "go", "hit": "walk about"}
    assert expected_gloss(g, "hit", "*") == "walk about; go"
    assert expected_gloss(g, "qal", "*") == "go"
    assert expected_gloss({"piel": "speak"}, "qal", "*") == "speak"
    assert expected_gloss({}, "qal", "*") == ""


# --- sessions ----------------------------------------------------------------

def test_new_card_limit_and_learning(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=3), clock)
    assert s.counts().new == 3
    shown = []
    for _ in range(3):
        item = s.next_item()
        assert item.is_new
        shown.append(item.key.lex_id)
        out = s.answer(item, "wrong answer", 3000)
        assert out.rating == Rating.Again and out.state == State.Learning
    assert shown == ["hbo:W", "hbo:H", "hbo:L"]
    assert s.counts().new == 0
    # Daily dose done: nothing is shown until a word in learning is due (1 min).
    assert s.next_item() is None
    due, waiting = s.next_learning_due()
    assert waiting == 3 and due == clock.now + timedelta(minutes=1)
    clock.advance(minutes=1)
    item = s.next_item()
    assert item is not None and not item.is_new
    # Nothing new the same day, even after all learning is done.
    clock.advance(hours=2)
    while (item := s.next_item()) is not None:
        s.rate(item, Rating.Good)
    assert s.counts().new == 0
    # The next day there are new cards again.
    clock.advance(days=1)
    assert s.counts().new == 3


def test_cards_graduate_and_come_back(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=1), clock)
    item = s.next_item()
    s.rate(item, Rating.Good)            # learning step 1 -> 2
    clock.advance(minutes=10)
    item = s.next_item()
    out = s.rate(item, Rating.Good)      # graduates
    assert out.state == State.Review
    assert out.due - clock.now >= timedelta(days=1)
    assert s.next_item() is None
    clock.now = out.due + timedelta(minutes=1)
    s = session(store, None, clock)      # a new day, a new session
    item = s.next_item()
    assert item.key.lex_id == "hbo:W" and not item.is_new
    assert s.counts().review >= 1


def test_review_shows_new_form(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=1), clock)
    first = s.next_item()
    s.rate(first, Rating.Again)
    clock.advance(minutes=2)
    second = s.next_item()
    assert second.key == first.key
    assert strip_accents(store.word(second.node)["form_utf8"]) != \
        strip_accents(store.word(first.node)["form_utf8"])


def test_typed_answer_correct(store, clock):
    s = session(store, DeckConfig(pos=["verb"], rank_max=50, new_per_day=1), clock)
    item = s.next_item()
    assert item.key.lex_id == "hbo:>MR["
    assert "say" in item.expected
    out = s.answer(item, "to say", 4000)
    assert out.result.correct and out.rating == Rating.Good
    row = store.con.execute("SELECT * FROM reviews").fetchone()
    assert row["correct"] == 1 and row["state_before"] == 0 and row["node"] == item.node


def test_cards_shared_between_decks(store, clock):
    s1 = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=1), clock, "a")
    s1.rate(s1.next_item(), Rating.Easy)
    s2 = session(store, DeckConfig(rank_max=5, new_per_day=5), clock, "b")
    item = s2.next_item()
    assert item.key.lex_id != "hbo:W"    # already known from deck a, not due


def test_review_limit(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=5,
                                  max_reviews_per_day=2), clock)
    for _ in range(5):
        s.rate(s.next_item(), Rating.Easy)   # Easy on a new card graduates at once
    clock.advance(days=60)
    assert s.counts().review == 2
    s.rate(s.next_item(), Rating.Good)
    s.rate(s.next_item(), Rating.Good)
    item = s.next_item()
    assert item is None or item.is_new


def test_day_start():
    assert day_start(datetime(2026, 3, 2, 10, tzinfo=UTC), UTC) == datetime(2026, 3, 2, 4, tzinfo=UTC)
    assert day_start(datetime(2026, 3, 2, 3, tzinfo=UTC), UTC) == datetime(2026, 3, 1, 4, tzinfo=UTC)


# --- migration ---------------------------------------------------------------

def test_import_score_csv(store, tmp_path):
    node = store.con.execute("SELECT node FROM bhsa.words WHERE lex_id='hbo:>MR[' LIMIT 1").fetchone()[0]
    now = datetime.now(UTC).timestamp()
    csv = tmp_path / "English_score.csv"
    csv.write_text("lex,node,time_score,time_stamp,rep\n"
                   f">MR[,{node},2.0,{now - 86400},1\n"
                   f">B/,1,8.0,{now - 86400},3\n"
                   f"XYZ/,,3.0,{now},1\n", encoding="utf-8")
    report = import_score_csv(store, csv)
    assert (report.imported, report.unknown) == (2, 1)
    cards = {r["lex_id"]: r for r in store.con.execute("SELECT * FROM cards")}
    assert cards["hbo:>MR["]["state"] == State.Review
    assert cards["hbo:>MR["]["stability"] > cards["hbo:>B/"]["stability"]   # faster, fewer mistakes
    assert cards["hbo:>B/"]["difficulty"] > cards["hbo:>MR["]["difficulty"]
    assert import_score_csv(store, csv).skipped_existing == 2


def test_elided_article_is_never_shown(store):
    # The article is often elided after a preposition and has no written form.
    rows = decks.occurrences(store.con, DeckConfig(), CardKey("hbo:H", "*"))
    assert rows and all(form for _, form in rows)


def test_qere_ketiv_cases_left_out(store):
    # NJWT/ (Naioth) only occurs as a ketiv with a qere: in no deck at all.
    for cfg in (DeckConfig(plan_id="hebrew-frequency"), DeckConfig(suffix="without")):
        assert "hbo:NJWT/" not in {k.lex_id for k in decks.deck_cards(store.con, cfg)}
    # A common word with some qere/ketiv occurrences: those are never shown.
    nodes = [n for n, _ in decks.occurrences(store.con, DeckConfig(), CardKey("hbo:HJH[", "*"))]
    qere = {r[0] for r in store.con.execute(
        "SELECT node FROM bhsa.words WHERE lex_id = 'hbo:HJH[' AND qere_utf8 IS NOT NULL")}
    assert qere and nodes and not qere & set(nodes)


def test_no_learn_ahead(store, clock):
    """Like Anki finishing a session: a card due in 10 minutes is not shown early."""
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=1), clock)
    s.rate(s.next_item(), Rating.Good)          # next learning step: 10 minutes
    assert s.next_item() is None
    clock.advance(minutes=9)
    assert s.next_item() is None
    clock.advance(minutes=1)
    assert s.next_item() is not None


def test_next_learning_due_only_today(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=1), clock)
    assert s.next_learning_due() is None
    s.rate(s.next_item(), Rating.Easy)          # graduates: due in days, not today
    assert s.next_learning_due() is None


def test_learning_count_includes_later_today(store, clock):
    s = session(store, DeckConfig(plan_id="hebrew-frequency", new_per_day=3), clock)
    s.rate(s.next_item(), Rating.Again)       # back in 1 min
    s.rate(s.next_item(), Rating.Good)        # back in 10 min
    c = s.counts()
    assert (c.learning, c.learning_today) == (0, 2)   # a wrong answer is counted at once
    clock.advance(minutes=1)
    c = s.counts()
    assert (c.learning, c.learning_today) == (1, 2)
