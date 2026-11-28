"""Statistics: progress, review history, forecast and how much of the text is known.

A word counts as *learned* when its card has graduated (FSRS state Review).
As in Anki, a learned word is *mature* when its current interval (from its last
review to its next) is 21 days or more, and *young* otherwise.
Coverage counts word occurrences in the Bible whose lexeme is learned (for
cards per stem: whose lexeme and stem are learned).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from fsrs import State

from . import decks as decks_mod
from .decks import Deck, deck_cards
from .session import DAY_ROLLOVER_HOUR, day_start
from .store import Store, parse_ts, ts


MATURE_DAYS = 21    # Anki's limit between young and mature words


def study_day(moment: datetime, tz: tzinfo | None = None) -> date:
    """The study day a moment belongs to (days start at 04:00 local)."""
    return (moment.astimezone(tz) - timedelta(hours=DAY_ROLLOVER_HOUR)).date()


def interval_days(last_review: str | None, due: str, tz: tzinfo | None = None) -> int:
    """A learned word's current interval in study days (0 if never reviewed here)."""
    if not last_review:
        return 0
    return (study_day(parse_ts(due), tz) - study_day(parse_ts(last_review), tz)).days


def is_mature(last_review: str | None, due: str, tz: tzinfo | None = None) -> bool:
    return interval_days(last_review, due, tz) >= MATURE_DAYS


def _in_corpus(corpus: str | None, column: str = "lex_id") -> tuple[str, tuple]:
    """SQL condition limiting cards (by lex_id) or reviews (by card_id) to a corpus."""
    if corpus is None:
        return "1", ()
    lexemes = "SELECT lex_id FROM bhsa.lexemes WHERE corpus = ?"
    if column == "card_id":
        return f"card_id IN (SELECT card_id FROM cards WHERE lex_id IN ({lexemes}))", (corpus,)
    return f"lex_id IN ({lexemes})", (corpus,)


def _maturity(store: Store, tz: tzinfo | None = None,
              corpus: str | None = None) -> dict[tuple[str, str], bool]:
    """(lex_id, stem) of every learned word (of a corpus, or all) -> mature?"""
    where, params = _in_corpus(corpus)
    return {(r[0], r[1]): is_mature(r[2], r[3], tz) for r in store.con.execute(
        f"SELECT lex_id, stem, last_review, due FROM cards WHERE state = ? AND {where}",
        (int(State.Review), *params))}


@dataclass
class Summary:
    learned: int                  # young + mature
    young: int
    mature: int
    learning: int
    reviews_total: int
    reviews_today: int
    retention_30d: float | None   # share of reviews of learned words answered correctly
    retention_young: float | None
    retention_mature: float | None
    streak_days: int              # consecutive study days up to today (or yesterday)


def summary(store: Store, now: datetime | None = None, tz: tzinfo | None = None, *,
            corpus: str | None = None) -> Summary:
    """Overview figures for all your words, or for one corpus ('bhsa', 'n1904')."""
    now = now or datetime.now(timezone.utc)
    con = store.con
    maturity = _maturity(store, tz, corpus)
    mature = sum(maturity.values())
    learned = len(maturity)
    cards_where, cards_params = _in_corpus(corpus)
    reviews_where, reviews_params = _in_corpus(corpus, "card_id")
    learning = con.execute(f"SELECT COUNT(*) FROM cards WHERE state IN (1, 3) AND {cards_where}",
                           cards_params).fetchone()[0]
    total = con.execute(f"SELECT COUNT(*) FROM reviews WHERE {reviews_where}",
                        reviews_params).fetchone()[0]
    today = con.execute(f"SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ? AND {reviews_where}",
                        (ts(day_start(now, tz)), *reviews_params)).fetchone()[0]

    # Retention over the last 30 days, split like Anki by the interval before the
    # review: a review is "mature" if the word had gone 21 days or more since its
    # previous review. (Words imported from the notebook version have no previous
    # review here; their first review counts as young.)
    since = ts(now - timedelta(days=30))
    tally = {False: [0, 0], True: [0, 0]}       # mature? -> [reviews, remembered]
    previous: dict[int, str] = {}
    for card_id, at, rating, state_before in con.execute(
            f"SELECT card_id, reviewed_at, rating, state_before FROM reviews WHERE {reviews_where} "
            "ORDER BY card_id, reviewed_at, review_id", reviews_params):
        if state_before == State.Review and at >= since:
            prev = previous.get(card_id)
            was_mature = bool(prev) and (study_day(parse_ts(at), tz)
                                         - study_day(parse_ts(prev), tz)).days >= MATURE_DAYS
            tally[was_mature][0] += 1
            tally[was_mature][1] += rating > 1
        previous[card_id] = at
    n = tally[False][0] + tally[True][0]
    ok = tally[False][1] + tally[True][1]

    def share(t):
        return t[1] / t[0] if t[0] else None
    days = {study_day(parse_ts(r[0]), tz) for r in con.execute(
        f"SELECT reviewed_at FROM reviews WHERE {reviews_where}", reviews_params)}
    streak, day = 0, study_day(now, tz)
    if day not in days:
        day -= timedelta(days=1)          # not studied yet today: count up to yesterday
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return Summary(learned, learned - mature, mature, learning, total, today,
                   ok / n if n else None, share(tally[False]), share(tally[True]), streak)


def reviews_per_day(store: Store, days: int = 30, now: datetime | None = None,
                    tz: tzinfo | None = None, *, corpus: str | None = None) -> list[tuple[date, int]]:
    """Number of reviews on each of the last `days` study days, oldest first."""
    where, params = _in_corpus(corpus, "card_id")
    now = now or datetime.now(timezone.utc)
    last = study_day(now, tz)
    first = last - timedelta(days=days - 1)
    counts = {first + timedelta(days=i): 0 for i in range(days)}
    since = ts(day_start(now, tz) - timedelta(days=days - 1))
    for (at,) in store.con.execute(f"SELECT reviewed_at FROM reviews WHERE reviewed_at >= ? AND {where}",
                                   (since, *params)):
        d = study_day(parse_ts(at), tz)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def forecast(store: Store, days: int = 30, now: datetime | None = None,
             tz: tzinfo | None = None, *, corpus: str | None = None) -> list[tuple[date, int]]:
    """Learned words falling due on each of the next `days` study days (overdue ones today)."""
    where, params = _in_corpus(corpus)
    now = now or datetime.now(timezone.utc)
    today = study_day(now, tz)
    counts = {today + timedelta(days=i): 0 for i in range(days)}
    for (due,) in store.con.execute(f"SELECT due FROM cards WHERE state = ? AND {where}",
                                    (int(State.Review), *params)):
        d = max(study_day(parse_ts(due), tz), today)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def word_counts(con) -> list[tuple[str, str, int, int]]:
    """(lex_id, stem, book_order, number of occurrences), counted once per run.

    Each book is a contiguous range of word nodes, so one grouped query per book
    range is much faster than joining every word with its verse.
    """
    def compute():
        cur = con.cursor()
        cur.row_factory = None
        ranges = cur.execute("""
            SELECT v.book_order, MIN(w.node), MAX(w.node) FROM bhsa.verses v
            JOIN bhsa.words w ON w.verse_id = v.verse_id GROUP BY v.book_order""").fetchall()
        rows = []
        for order, first, last in ranges:
            rows += [(lex, stem, order, n) for lex, stem, n in cur.execute(
                "SELECT lex_id, stem, COUNT(*) FROM bhsa.words WHERE node BETWEEN ? AND ? "
                "GROUP BY lex_id, stem", (first, last))]
        return rows
    return decks_mod._cached(con, ("word counts",), compute)


def _word_counts(store: Store) -> list[tuple[str, str, int, int]]:
    return word_counts(store.con)


def _book_names(store: Store) -> list[tuple[int, str, str]]:
    """(book_order, English name, corpus) in canonical order."""
    con = store.con
    return decks_mod._cached(con, ("book names",), lambda: [
        (r[0], r[1].replace("_", " "), r[2]) for r in con.execute(
            "SELECT book_order, book_en, corpus FROM bhsa.verses "
            "GROUP BY book_order ORDER BY book_order")])


def corpora_with_progress(store: Store) -> list[str]:
    """Corpora with at least one studied word, in the order of decks_mod.CORPORA."""
    used = {r[0] for r in store.con.execute(
        "SELECT DISTINCT l.corpus FROM cards c JOIN bhsa.lexemes l ON l.lex_id = c.lex_id")}
    return [c for c in decks_mod.CORPORA if c in used]


def _known_by_book(store: Store, tz: tzinfo | None = None) -> dict[int, list[int]]:
    """book_order -> [occurrences, occurrences of learned words, of mature words]."""
    maturity = _maturity(store, tz)
    whole = {lex: m for (lex, stem), m in maturity.items() if stem == "*"}
    totals: dict[int, list[int]] = {}
    for lex_id, stem, book, n in _word_counts(store):
        entry = totals.setdefault(book, [0, 0, 0])
        entry[0] += n
        mature = whole.get(lex_id)
        if mature is None:
            mature = maturity.get((lex_id, stem))
        if mature is not None:
            entry[1] += n
            if mature:
                entry[2] += n
    return totals


@dataclass
class Coverage:
    words: int       # word occurrences
    known: int       # of learned words (young and mature)
    mature: int      # of mature words

    @property
    def share(self) -> float:
        return self.known / self.words if self.words else 0.0

    @property
    def mature_share(self) -> float:
        return self.mature / self.words if self.words else 0.0


def coverage_detail(store: Store, corpus: str = "bhsa", tz: tzinfo | None = None) -> Coverage:
    """Coverage of one corpus (the Hebrew Bible by default, or 'n1904')."""
    totals = _known_by_book(store, tz)
    orders = [order for order, _name, c in _book_names(store) if c == corpus]
    rows = [totals.get(order, [0, 0, 0]) for order in orders]
    return Coverage(*(sum(t[i] for t in rows) for i in range(3)))


def coverage(store: Store, corpus: str = "bhsa") -> float:
    """Share of all word occurrences in a corpus whose word is learned."""
    return coverage_detail(store, corpus).share


@dataclass
class BookCoverage(Coverage):
    book: str = ""   # English name


def coverage_by_book(store: Store, tz: tzinfo | None = None,
                     corpus: str | None = None) -> list[BookCoverage]:
    """Coverage per book, of one corpus or (corpus=None) of all."""
    totals = _known_by_book(store, tz)
    return [BookCoverage(*totals.get(order, [0, 0, 0]), book=name)
            for order, name, c in _book_names(store) if corpus is None or c == corpus]


@dataclass
class DeckProgress:
    name: str
    total: int
    learned: int     # young + mature
    mature: int
    learning: int

    @property
    def young(self) -> int:
        return self.learned - self.mature


def deck_progress(store: Store, deck: Deck, tz: tzinfo | None = None) -> DeckProgress:
    keys = deck_cards(store.con, deck.config)
    maturity = _maturity(store, tz)
    in_learning = {(r[0], r[1]) for r in store.con.execute(
        "SELECT lex_id, stem FROM cards WHERE state IN (1, 3)")}
    learned = [maturity[k] for k in map(tuple, keys) if k in maturity]
    learning = sum(1 for k in map(tuple, keys) if k in in_learning)
    return DeckProgress(deck.name, len(keys), len(learned), sum(learned), learning)
