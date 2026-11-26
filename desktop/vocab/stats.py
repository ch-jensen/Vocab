"""Statistics: progress, review history, forecast and how much of the text is known.

A word counts as *learned* when its card has graduated (FSRS state Review).
Coverage counts word occurrences in the Bible whose lexeme is learned (for
cards per stem: whose lexeme and stem are learned).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from fsrs import State

from .decks import Deck, deck_cards
from .session import DAY_ROLLOVER_HOUR, day_start
from .store import Store, parse_ts, ts


def study_day(moment: datetime, tz: tzinfo | None = None) -> date:
    """The study day a moment belongs to (days start at 04:00 local)."""
    return (moment.astimezone(tz) - timedelta(hours=DAY_ROLLOVER_HOUR)).date()


@dataclass
class Summary:
    learned: int
    learning: int
    reviews_total: int
    reviews_today: int
    retention_30d: float | None   # share of reviews of learned words answered correctly
    streak_days: int              # consecutive study days up to today (or yesterday)


def summary(store: Store, now: datetime | None = None, tz: tzinfo | None = None) -> Summary:
    now = now or datetime.now(timezone.utc)
    con = store.con
    learned, learning = con.execute(
        "SELECT COALESCE(SUM(state = 2), 0), COALESCE(SUM(state IN (1, 3)), 0) FROM cards").fetchone()
    total = con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    today = con.execute("SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ?",
                        (ts(day_start(now, tz)),)).fetchone()[0]
    n, ok = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(rating > 1), 0) FROM reviews "
        "WHERE state_before = ? AND reviewed_at >= ?",
        (int(State.Review), ts(now - timedelta(days=30)))).fetchone()
    days = {study_day(parse_ts(r[0]), tz) for r in con.execute("SELECT reviewed_at FROM reviews")}
    streak, day = 0, study_day(now, tz)
    if day not in days:
        day -= timedelta(days=1)          # not studied yet today: count up to yesterday
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return Summary(learned, learning, total, today, ok / n if n else None, streak)


def reviews_per_day(store: Store, days: int = 30, now: datetime | None = None,
                    tz: tzinfo | None = None) -> list[tuple[date, int]]:
    """Number of reviews on each of the last `days` study days, oldest first."""
    now = now or datetime.now(timezone.utc)
    last = study_day(now, tz)
    first = last - timedelta(days=days - 1)
    counts = {first + timedelta(days=i): 0 for i in range(days)}
    since = ts(day_start(now, tz) - timedelta(days=days - 1))
    for (at,) in store.con.execute("SELECT reviewed_at FROM reviews WHERE reviewed_at >= ?", (since,)):
        d = study_day(parse_ts(at), tz)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def forecast(store: Store, days: int = 30, now: datetime | None = None,
             tz: tzinfo | None = None) -> list[tuple[date, int]]:
    """Learned words falling due on each of the next `days` study days (overdue ones today)."""
    now = now or datetime.now(timezone.utc)
    today = study_day(now, tz)
    counts = {today + timedelta(days=i): 0 for i in range(days)}
    for (due,) in store.con.execute("SELECT due FROM cards WHERE state = ?", (int(State.Review),)):
        d = max(study_day(parse_ts(due), tz), today)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


_KNOWN = """EXISTS (SELECT 1 FROM cards c WHERE c.lex_id = w.lex_id AND c.state = 2
                    AND (c.stem = '*' OR c.stem = w.stem))"""


def coverage(store: Store) -> float:
    """Share of all word occurrences in the Bible whose word is learned."""
    total, known = store.con.execute(
        f"SELECT COUNT(*), COALESCE(SUM({_KNOWN}), 0) FROM bhsa.words w").fetchone()
    return known / total if total else 0.0


@dataclass
class BookCoverage:
    book: str        # English name
    words: int       # word occurrences in the book
    known: int

    @property
    def share(self) -> float:
        return self.known / self.words if self.words else 0.0


def coverage_by_book(store: Store) -> list[BookCoverage]:
    rows = store.con.execute(f"""
        SELECT v.book_en, COUNT(*), COALESCE(SUM({_KNOWN}), 0)
        FROM bhsa.words w JOIN bhsa.verses v ON v.verse_id = w.verse_id
        GROUP BY v.book_order ORDER BY v.book_order""").fetchall()
    return [BookCoverage(r[0].replace("_", " "), r[1], r[2]) for r in rows]


@dataclass
class DeckProgress:
    name: str
    total: int
    learned: int
    learning: int


def deck_progress(store: Store, deck: Deck) -> DeckProgress:
    keys = deck_cards(store.con, deck.config)
    states: dict[tuple[str, str], int] = {
        (r[0], r[1]): r[2] for r in store.con.execute("SELECT lex_id, stem, state FROM cards")}
    learned = sum(1 for k in keys if states.get(tuple(k)) == State.Review)
    learning = sum(1 for k in keys if states.get(tuple(k)) in (State.Learning, State.Relearning))
    return DeckProgress(deck.name, len(keys), learned, learning)
