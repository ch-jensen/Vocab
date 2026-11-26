"""Deck definitions and the SQL that turns them into card keys and occurrences.

A deck is either a predefined plan (lexemes in a fixed order) or a set of
filters, like the widgets in the notebook version. Filters come in two kinds:

* lexeme filters: language, part of speech, frequency rank, plan, gloss language
* occurrence filters: verbal stem, tense, pronominal suffix, passage

A lexeme belongs to the deck if at least one of its occurrences passes all
filters. When a card is studied, the occurrence shown is drawn from the
occurrences that pass the occurrence filters. As in the notebook version, the
stem and tense filters only apply to verbs.

Some occurrences are never asked about (see ASKABLE): qere/ketiv cases, and
words with no written form (mostly the article elided after a preposition, as
in לַמֶּלֶךְ). A lexeme attested only in such occurrences is in no deck.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple

from .store import Store, ts

ALL_STEMS = "*"   # card stem for a whole-lexeme card

# Condition on bhsa.words w for occurrences that can be shown as a question.
ASKABLE = "(w.qere_utf8 IS NULL AND w.form_utf8 <> '')"


class CardKey(NamedTuple):
    lex_id: str
    stem: str     # '*' or a BHSA stem such as 'piel'


@dataclass
class Passage:
    book: str                       # BHSA book name, e.g. 'Genesis', 'Jona'
    chapter_from: int | None = None
    chapter_to: int | None = None


@dataclass
class DeckConfig:
    plan_id: str | None = None
    languages: list[str] = field(default_factory=lambda: ["Hebrew"])
    pos: list[str] | None = None          # BHSA sp values; None = all
    rank_min: int | None = None           # BHSA rank_lex, 0 = most frequent
    rank_max: int | None = None
    stems: list[str] | None = None        # verbs only; None = all
    tenses: list[str] | None = None       # verbs only; None = all
    suffix: str = "any"                   # 'any' | 'with' | 'without'
    passages: list[Passage] | None = None
    include_lex: list[str] = field(default_factory=list)
    exclude_lex: list[str] = field(default_factory=list)
    split_stems: bool = False             # one card per verbal stem
    gloss_language: str = "English"
    new_per_day: int = 10
    max_reviews_per_day: int = 200
    desired_retention: float = 0.9
    answer_mode: str = "typed"            # 'typed' | 'self' (show answer, rate yourself)
    show_lexeme: bool = False             # show the dictionary form with the question

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "DeckConfig":
        data = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in data.items() if k in known}
        if data.get("passages"):
            data["passages"] = [Passage(**p) for p in data["passages"]]
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.suffix not in ("any", "with", "without"):
            raise ValueError(f"suffix must be any/with/without, not {self.suffix!r}")
        if self.answer_mode not in ("typed", "self"):
            raise ValueError(f"answer_mode must be typed/self, not {self.answer_mode!r}")
        if not 0.5 <= self.desired_retention <= 0.99:
            raise ValueError("desired_retention must be between 0.5 and 0.99")
        if self.new_per_day < 0 or self.max_reviews_per_day < 0:
            raise ValueError("daily limits cannot be negative")


def _in(column: str, values: list) -> tuple[str, list]:
    return f"{column} IN ({','.join('?' * len(values))})", list(values)


def occurrence_conditions(cfg: DeckConfig) -> tuple[list[str], list]:
    """Conditions on bhsa.words w joined with bhsa.verses v."""
    conds, params = [], []
    if cfg.stems is not None:
        sql, p = _in("w.stem", cfg.stems)
        conds.append(f"(w.sp <> 'verb' OR {sql})")
        params += p
    if cfg.tenses is not None:
        sql, p = _in("w.tense", cfg.tenses)
        conds.append(f"(w.sp <> 'verb' OR {sql})")
        params += p
    if cfg.suffix == "with":
        conds.append("w.has_suffix = 1")
    elif cfg.suffix == "without":
        conds.append("w.has_suffix = 0")
    if cfg.passages:
        ors = []
        for p in cfg.passages:
            ors.append("(v.book = ? AND v.chapter BETWEEN ? AND ?)")
            params += [p.book, p.chapter_from or 1, p.chapter_to or 999]
        conds.append("(" + " OR ".join(ors) + ")")
    return conds, params


def lexeme_conditions(cfg: DeckConfig) -> tuple[list[str], list]:
    """Conditions on bhsa.lexemes l (and w.lex_id)."""
    conds, params = [], []
    if cfg.languages:
        sql, p = _in("l.language", cfg.languages)
        conds.append(sql)
        params += p
    if cfg.pos is not None:
        sql, p = _in("l.sp", cfg.pos)
        conds.append(sql)
        params += p
    if cfg.rank_min is not None:
        conds.append("l.rank >= ?")
        params.append(cfg.rank_min)
    if cfg.rank_max is not None:
        conds.append("l.rank <= ?")
        params.append(cfg.rank_max)
    if cfg.plan_id:
        conds.append("l.lex_id IN (SELECT lex_id FROM bhsa.plan_items WHERE plan_id = ?)")
        params.append(cfg.plan_id)
    if cfg.gloss_language != "English":
        conds.append("(EXISTS (SELECT 1 FROM bhsa.glosses g WHERE g.lex_id = l.lex_id "
                     "AND g.gloss_language = ?) OR EXISTS (SELECT 1 FROM user_glosses u "
                     "WHERE u.lex_id = l.lex_id AND u.gloss_language = ?))")
        params += [cfg.gloss_language, cfg.gloss_language]
    return conds, params


def deck_cards(con: sqlite3.Connection, cfg: DeckConfig) -> list[CardKey]:
    """All card keys of a deck, in the order new cards are introduced.

    Plan decks follow the plan order; filter decks go from the most to the least
    frequent lexeme. With split_stems, a verb's stems follow each other, most
    frequent stem first.
    """
    lex_conds, lex_params = lexeme_conditions(cfg)
    occ_conds, occ_params = occurrence_conditions(cfg)
    where = " AND ".join(lex_conds + occ_conds) or "1"
    params: list = [int(cfg.split_stems)]
    plan_join = ""
    if cfg.plan_id:
        plan_join = "LEFT JOIN bhsa.plan_items p ON p.lex_id = w.lex_id AND p.plan_id = ?"
        params.append(cfg.plan_id)
    params += lex_params + occ_params

    include = ""
    if cfg.include_lex:
        sql, p = _in("w.lex_id", cfg.include_lex)
        include = f" OR {sql}"
        params += p
    exclude = ""
    if cfg.exclude_lex:
        sql, p = _in("w.lex_id", cfg.exclude_lex)
        exclude = f" AND NOT {sql}"
        params += p

    order_pos = "COALESCE(MIN(p.position), 1000000000)" if cfg.plan_id else "0"
    if occ_conds:
        # Occurrence filters: look at every word.
        source = ("bhsa.words w JOIN bhsa.verses v ON v.verse_id = w.verse_id", "COUNT(*)")
        askable = ASKABLE
    else:
        # Lexeme filters only: the per-stem counts are enough (much faster).
        source = ("bhsa.lexeme_stems w", "SUM(w.freq)")
        askable = (f"EXISTS (SELECT 1 FROM bhsa.words x WHERE x.lex_id = w.lex_id "
                   f"AND x.stem = w.stem AND {ASKABLE.replace('w.', 'x.')})")
    rows = con.execute(f"""
        SELECT w.lex_id,
               CASE WHEN ? AND w.stem <> 'NA' THEN w.stem ELSE '*' END AS card_stem,
               {source[1]} AS n, MIN(l.freq) AS lex_freq, {order_pos} AS plan_pos
        FROM {source[0]}
        JOIN bhsa.lexemes l ON l.lex_id = w.lex_id
        {plan_join}
        WHERE (({where}){include}){exclude} AND {askable}
        GROUP BY w.lex_id, card_stem
        ORDER BY plan_pos, lex_freq DESC, w.lex_id, n DESC
    """, params).fetchall()
    return [CardKey(r[0], r[1]) for r in rows]


def occurrences(con: sqlite3.Connection, cfg: DeckConfig, key: CardKey) -> list[sqlite3.Row]:
    """Occurrences (node, form_utf8) of a card that pass the occurrence filters.

    Only askable occurrences are returned (see ASKABLE). Falls back to all
    askable occurrences of the card when none pass the filters (e.g. for a
    lexeme the user added by hand).
    """
    base = ("SELECT w.node, w.form_utf8 FROM bhsa.words w "
            "JOIN bhsa.verses v ON v.verse_id = w.verse_id "
            f"WHERE w.lex_id = ? AND {ASKABLE}")
    params: list = [key.lex_id]
    if key.stem != ALL_STEMS:
        base += " AND w.stem = ?"
        params.append(key.stem)
    conds, occ_params = occurrence_conditions(cfg)
    if conds:
        rows = con.execute(base + " AND " + " AND ".join(conds) + " ORDER BY w.node",
                           params + occ_params).fetchall()
        if rows:
            return rows
    return con.execute(base + " ORDER BY w.node", params).fetchall()


# --- deck storage ------------------------------------------------------------

@dataclass
class Deck:
    deck_id: int
    name: str
    config: DeckConfig


def create_deck(store: Store, name: str, cfg: DeckConfig) -> Deck:
    cfg.validate()
    cur = store.con.execute("INSERT INTO decks (name, config, created_at) VALUES (?, ?, ?)",
                            (name, cfg.to_json(), ts(datetime.now(timezone.utc))))
    store.con.commit()
    return Deck(cur.lastrowid, name, cfg)


def update_deck(store: Store, deck: Deck) -> None:
    deck.config.validate()
    store.con.execute("UPDATE decks SET name = ?, config = ? WHERE deck_id = ?",
                      (deck.name, deck.config.to_json(), deck.deck_id))
    store.con.commit()


def delete_deck(store: Store, deck_id: int) -> None:
    """Delete a deck. Cards and review history are kept (they are shared)."""
    store.con.execute("DELETE FROM decks WHERE deck_id = ?", (deck_id,))
    store.con.commit()


def get_deck(store: Store, name_or_id: str | int) -> Deck | None:
    row = store.con.execute("SELECT deck_id, name, config FROM decks WHERE deck_id = ? OR name = ?",
                            (name_or_id, str(name_or_id))).fetchone()
    return Deck(row[0], row[1], DeckConfig.from_json(row[2])) if row else None


def list_decks(store: Store) -> list[Deck]:
    return [Deck(r[0], r[1], DeckConfig.from_json(r[2])) for r in
            store.con.execute("SELECT deck_id, name, config FROM decks ORDER BY name")]


def plans(store: Store) -> list[sqlite3.Row]:
    return store.con.execute(
        "SELECT p.plan_id, p.name, p.description, COUNT(i.lex_id) AS size "
        "FROM bhsa.plans p JOIN bhsa.plan_items i USING (plan_id) GROUP BY p.plan_id").fetchall()
