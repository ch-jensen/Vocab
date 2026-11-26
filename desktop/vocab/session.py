"""A study session on one deck: what to show next, and recording answers with FSRS.

Order of cards, as in Anki:
1. learning / relearning cards that are due,
2. review cards that are due (up to the deck's daily review limit),
3. new cards in deck order (up to the deck's daily new-card limit),
4. learning cards due within the next 20 minutes ("learn ahead").
The same lexeme is not shown twice in a row if anything else is available.

The day starts at 04:00 local time, as in Anki.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable

from fsrs import Card, Rating, Scheduler, State

from . import answers
from .decks import ALL_STEMS, CardKey, Deck, deck_cards, occurrences
from .occurrences import choose_occurrence
from .store import Store, parse_ts, ts

DAY_ROLLOVER_HOUR = 4
LEARN_AHEAD = timedelta(minutes=20)
NEW = 0  # state_before for a card's first review


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def day_start(now: datetime, tz: tzinfo | None = None) -> datetime:
    """Start of the study day containing `now` (04:00 local), in UTC."""
    local = now.astimezone(tz)
    start = local.replace(hour=DAY_ROLLOVER_HOUR, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


@dataclass
class ClauseWord:
    node: int
    form: str
    trailer: str
    qere: str | None


@dataclass
class StudyItem:
    key: CardKey
    card_id: int | None        # None for a new card
    is_new: bool
    node: int                  # the occurrence shown
    clause: list[ClauseWord]
    reference: str
    lex_utf8: str
    voc_lex_utf8: str
    sp: str
    freq: int
    rank: int
    stem: str                  # stem of this occurrence ('NA' for non-verbs)
    tense: str
    gloss: str                 # gloss text to show after answering
    expected: list[str]        # accepted answers


@dataclass
class Outcome:
    rating: Rating
    result: answers.AnswerResult | None   # None when self-graded
    gloss: str
    due: datetime
    state: State


@dataclass
class Counts:
    new: int
    learning: int
    review: int


def expected_gloss(glosses: dict[str, str], occurrence_stem: str, card_stem: str) -> str:
    """Gloss for an occurrence: its stem's gloss and/or the default gloss."""
    stem = card_stem if card_stem != ALL_STEMS else occurrence_stem
    parts = [glosses[s] for s in (stem, "default") if s in glosses and s != "NA"]
    if not parts and glosses:
        parts = [next(iter(glosses.values()))]
    return "; ".join(dict.fromkeys(parts))


def card_from_row(row: sqlite3.Row) -> Card:
    return Card(card_id=row["card_id"], state=State(row["state"]), step=row["step"],
                stability=row["stability"], difficulty=row["difficulty"],
                due=parse_ts(row["due"]), last_review=parse_ts(row["last_review"]))


def fsrs_parameters(store: Store) -> list[float] | None:
    """Parameters fitted to this user's history, if the optimiser has been run."""
    value = store.get_meta("fsrs_parameters")
    return json.loads(value) if value else None


class StudySession:
    def __init__(self, store: Store, deck: Deck, *,
                 clock: Callable[[], datetime] = utcnow,
                 tz: tzinfo | None = None,
                 rng: random.Random | None = None,
                 fuzzing: bool = True):
        self.store = store
        self.con = store.con
        self.deck = deck
        self.cfg = deck.config
        self.clock = clock
        self.tz = tz
        self.rng = rng or random.Random()
        params = fsrs_parameters(store)
        kwargs = {"parameters": params} if params else {}
        self.scheduler = Scheduler(desired_retention=self.cfg.desired_retention,
                                   enable_fuzzing=fuzzing, **kwargs)
        self.keys = deck_cards(self.con, self.cfg)
        self._load_keys()
        self.last_lex: str | None = None

    # --- queue -------------------------------------------------------------
    def _load_keys(self) -> None:
        self.con.execute("DROP TABLE IF EXISTS temp.deck_keys")
        self.con.execute("CREATE TEMP TABLE deck_keys (lex_id TEXT, stem TEXT, ord INTEGER, "
                         "PRIMARY KEY (lex_id, stem))")
        self.con.executemany("INSERT INTO temp.deck_keys VALUES (?, ?, ?)",
                             [(k.lex_id, k.stem, i) for i, k in enumerate(self.keys)])

    def _done_today(self) -> tuple[int, int]:
        """(new cards introduced today, review cards reviewed today) in this deck."""
        since = ts(day_start(self.clock(), self.tz))
        row = self.con.execute("""
            SELECT COUNT(DISTINCT CASE WHEN state_before = 0 THEN card_id END),
                   COUNT(DISTINCT CASE WHEN state_before = 2 THEN card_id END)
            FROM reviews WHERE deck_id = ? AND reviewed_at >= ?""",
            (self.deck.deck_id, since)).fetchone()
        return row[0], row[1]

    def counts(self) -> Counts:
        now = ts(self.clock())
        new_today, reviews_today = self._done_today()
        learning, review = self.con.execute("""
            SELECT COALESCE(SUM(c.state IN (1, 3)), 0), COALESCE(SUM(c.state = 2), 0)
            FROM cards c JOIN temp.deck_keys k ON k.lex_id = c.lex_id AND k.stem = c.stem
            WHERE c.due <= ?""", (now,)).fetchone()
        unseen = self.con.execute("""
            SELECT COUNT(*) FROM temp.deck_keys k
            WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.lex_id = k.lex_id AND c.stem = k.stem)
            """).fetchone()[0]
        return Counts(new=min(unseen, max(self.cfg.new_per_day - new_today, 0)),
                      learning=learning,
                      review=min(review, max(self.cfg.max_reviews_per_day - reviews_today, 0)))

    def _due_cards(self, states: tuple[int, ...], until: datetime, limit: int) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(states))
        return self.con.execute(f"""
            SELECT c.* FROM cards c
            JOIN temp.deck_keys k ON k.lex_id = c.lex_id AND k.stem = c.stem
            WHERE c.state IN ({marks}) AND c.due <= ?
            ORDER BY c.due LIMIT ?""", (*states, ts(until), limit)).fetchall()

    def _new_keys(self, limit: int) -> list[CardKey]:
        return [CardKey(r[0], r[1]) for r in self.con.execute("""
            SELECT k.lex_id, k.stem FROM temp.deck_keys k
            WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.lex_id = k.lex_id AND c.stem = k.stem)
            ORDER BY k.ord LIMIT ?""", (limit,))]

    def _candidates(self) -> list[tuple[CardKey, sqlite3.Row | None]]:
        now = self.clock()
        new_today, reviews_today = self._done_today()
        out: list[tuple[CardKey, sqlite3.Row | None]] = []
        for row in self._due_cards((State.Learning, State.Relearning), now, 2):
            out.append((CardKey(row["lex_id"], row["stem"]), row))
        review_left = self.cfg.max_reviews_per_day - reviews_today
        if review_left > 0:
            for row in self._due_cards((State.Review,), now, min(review_left, 2)):
                out.append((CardKey(row["lex_id"], row["stem"]), row))
        new_left = self.cfg.new_per_day - new_today
        if new_left > 0:
            out += [(k, None) for k in self._new_keys(min(new_left, 2))]
        if not out:
            for row in self._due_cards((State.Learning, State.Relearning), now + LEARN_AHEAD, 2):
                out.append((CardKey(row["lex_id"], row["stem"]), row))
        return out

    def next_item(self) -> StudyItem | None:
        candidates = self._candidates()
        if not candidates:
            return None
        others = [c for c in candidates if c[0].lex_id != self.last_lex]
        key, row = (others or candidates)[0]
        return self._make_item(key, row)

    # --- building an item --------------------------------------------------
    def _make_item(self, key: CardKey, row: sqlite3.Row | None) -> StudyItem:
        card_id = row["card_id"] if row else None
        last_shown = {}
        if card_id is not None:
            last_shown = {r[0]: r[1] for r in self.con.execute(
                "SELECT node, MAX(reviewed_at) FROM reviews WHERE card_id = ? AND node IS NOT NULL "
                "GROUP BY node", (card_id,))}
        node = choose_occurrence(occurrences(self.con, self.cfg, key), last_shown, self.rng)
        word = self.store.word(node)
        lex = self.store.lexeme(key.lex_id)
        glosses = self.store.glosses(key.lex_id, self.cfg.gloss_language)
        gloss = expected_gloss(glosses, word["stem"], key.stem)
        return StudyItem(
            key=key, card_id=card_id, is_new=row is None, node=node,
            clause=[ClauseWord(r[0], r[1], r[2], r[3]) for r in self.store.clause_words(word["clause_id"])],
            reference=self.store.reference(word["verse_id"]),
            lex_utf8=lex["lex_utf8"], voc_lex_utf8=lex["voc_lex_utf8"], sp=lex["sp"],
            freq=lex["freq"], rank=lex["rank"], stem=word["stem"], tense=word["tense"],
            gloss=gloss, expected=answers.split_glosses(gloss),
        )

    # --- answering ---------------------------------------------------------
    def reference_ms(self) -> float:
        rows = self.con.execute(
            "SELECT duration_ms FROM reviews WHERE mode = 'typed' AND correct = 1 "
            "AND duration_ms IS NOT NULL ORDER BY reviewed_at DESC LIMIT 100").fetchall()
        return answers.reference_time([r[0] for r in rows])

    def answer(self, item: StudyItem, text: str, duration_ms: int) -> Outcome:
        """Record a typed answer; the rating is derived from correctness and time."""
        result = answers.check_answer(text, item.expected)
        rating = answers.rating_for(result, duration_ms, self.reference_ms(), item.is_new)
        return self._record(item, rating, duration_ms, "typed", text, result)

    def rate(self, item: StudyItem, rating: Rating, duration_ms: int | None = None) -> Outcome:
        """Record a self-graded review (Anki's 'show answer' mode)."""
        return self._record(item, Rating(rating), duration_ms, "self", None, None)

    def _record(self, item: StudyItem, rating: Rating, duration_ms: int | None, mode: str,
                text: str | None, result: answers.AnswerResult | None) -> Outcome:
        now = self.clock()
        if item.card_id is None:
            row = self.con.execute("SELECT * FROM cards WHERE lex_id = ? AND stem = ?",
                                   item.key).fetchone()
        else:
            row = self.con.execute("SELECT * FROM cards WHERE card_id = ?", (item.card_id,)).fetchone()

        if row is None:
            cur = self.con.execute(
                "INSERT INTO cards (lex_id, stem, state, step, due, created_at) VALUES (?, ?, ?, 0, ?, ?)",
                (item.key.lex_id, item.key.stem, int(State.Learning), ts(now), ts(now)))
            card = Card(card_id=cur.lastrowid, state=State.Learning, due=now)
            state_before = NEW
        else:
            card = card_from_row(row)
            state_before = int(card.state)

        card, _log = self.scheduler.review_card(card, rating, now, duration_ms)
        self.con.execute("""
            UPDATE cards SET state = ?, step = ?, stability = ?, difficulty = ?, due = ?, last_review = ?
            WHERE card_id = ?""",
            (int(card.state), card.step, card.stability, card.difficulty, ts(card.due),
             ts(card.last_review) if card.last_review else None, card.card_id))
        self.con.execute("""
            INSERT INTO reviews (card_id, deck_id, node, reviewed_at, rating, duration_ms, mode,
                                 answer, correct, typo, state_before)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card.card_id, self.deck.deck_id, item.node, ts(now), int(rating), duration_ms, mode,
             text, None if result is None else int(result.correct),
             int(bool(result and result.typo)), state_before))
        self.con.commit()
        self.last_lex = item.key.lex_id
        return Outcome(rating, result, item.gloss, card.due, card.state)
