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
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple

from .store import Store, ts

ALL_STEMS = "*"   # card stem for a whole-lexeme card

# The corpora in the database, with the languages each contains.
CORPORA = {"bhsa": "Hebrew Bible (BHSA)", "n1904": "Greek New Testament (Nestle 1904)"}
CORPUS_LANGUAGES = {"bhsa": ["Hebrew", "Aramaic"], "n1904": ["Greek"]}
RTL_LANGUAGES = {"Hebrew", "Aramaic"}

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


def parse_chapters(text: str, last: int) -> list[tuple[int, int]]:
    """'1-3; 11; 45-48' -> [(1, 3), (11, 11), (45, 48)]. Empty text means the whole book.

    Parts are separated by semicolons (commas also work); ranges use '-' or '–';
    single chapters are allowed. A book name or abbreviation at the start is
    ignored ('Genesis 1-3; 11'). Raises ValueError with a readable message.
    """
    text = re.sub(r"^\s*\d?\s*[^\W\d_][^\d;,]*?\s+(?=\d)", "", text).strip()
    if not text:
        return [(1, last)]
    ranges = []
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-–—]\s*(\d+))?", part)
        if not m:
            raise ValueError(f"“{part}” is not a chapter or a range (write e.g. 1-3; 11; 45-48)")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start > end:
            start, end = end, start
        if start < 1 or end > last:
            raise ValueError(f"“{part}”: the book has chapters 1–{last}")
        ranges.append((start, end))
    if not ranges:
        return [(1, last)]
    # Merge overlapping or adjacent ranges.
    ranges.sort()
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def format_chapters(ranges: list[tuple[int, int]], last: int) -> str:
    """[(1, 3), (11, 11), (45, 48)] -> '1–3; 11; 45–48'; the whole book -> ''."""
    if not ranges or ranges == [(1, last)]:
        return ""
    return "; ".join(str(a) if a == b else f"{a}–{b}" for a, b in ranges)


def passages_by_book(passages: list[Passage] | None) -> dict[str, list[tuple[int, int]]]:
    """Group passages by book, keeping open ends as None (= first/last chapter)."""
    out: dict[str, list[tuple[int, int]]] = {}
    for p in passages or []:
        out.setdefault(p.book, []).append((p.chapter_from or 1, p.chapter_to or 999))
    return out


@dataclass
class DeckConfig:
    plan_id: str | None = None
    corpus: str = "bhsa"                  # 'bhsa' (Hebrew Bible) | 'n1904' (Greek NT)
    languages: list[str] = field(default_factory=lambda: ["Hebrew"])
    pos: list[str] | None = None          # BHSA sp values; None = all
    rank_min: int | None = None           # BHSA rank_lex, 0 = most frequent
    rank_max: int | None = None
    stems: list[str] | None = None        # verbs only; None = all
    tenses: list[str] | None = None       # verbs only; None = all
    voices: list[str] | None = None       # Greek verbs only; None = all
    moods: list[str] | None = None        # Greek verbs only; None = all
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
        if self.corpus not in CORPORA:
            raise ValueError(f"unknown corpus {self.corpus!r}")
        if self.answer_mode not in ("typed", "self"):
            raise ValueError(f"answer_mode must be typed/self, not {self.answer_mode!r}")
        if not 0.5 <= self.desired_retention <= 0.99:
            raise ValueError("desired_retention must be between 0.5 and 0.99")
        if self.new_per_day < 0 or self.max_reviews_per_day < 0:
            raise ValueError("daily limits cannot be negative")


def _in(column: str, values: list) -> tuple[str, list]:
    return f"{column} IN ({','.join('?' * len(values))})", list(values)


def occurrence_conditions(cfg: DeckConfig, con: sqlite3.Connection) -> tuple[list[str], list]:
    """Conditions on bhsa.words w for the occurrence filters (stem, tense, suffix, passage).

    Passages are turned into ranges of word nodes: BHSA numbers the words in
    canonical order, so the words of a chapter range are one contiguous range.
    That lets SQLite use the indexes instead of looking up each word's verse.
    """
    conds, params = [], []
    if cfg.stems is not None:
        sql, p = _in("w.stem", cfg.stems)
        conds.append(f"(w.sp <> 'verb' OR {sql})")
        params += p
    if cfg.tenses is not None:
        sql, p = _in("w.tense", cfg.tenses)
        conds.append(f"(w.sp <> 'verb' OR {sql})")
        params += p
    for column, values in (("w.voice", cfg.voices), ("w.mood", cfg.moods)):
        if values is not None:
            sql, p = _in(column, values)
            conds.append(f"(w.sp <> 'verb' OR {sql})")
            params += p
    if cfg.suffix == "with":
        conds.append("w.has_suffix = 1")
    elif cfg.suffix == "without":
        conds.append("w.has_suffix = 0")
    if cfg.passages:
        ranges = [r for p in cfg.passages if (r := passage_nodes(con, p)) is not None]
        if ranges:
            conds.append("(" + " OR ".join("w.node BETWEEN ? AND ?" for _ in ranges) + ")")
            params += [n for r in ranges for n in r]
        else:
            conds.append("0")
    return conds, params


def lexeme_conditions(cfg: DeckConfig) -> tuple[list[str], list]:
    """Conditions on bhsa.lexemes l. (The plan and the gloss language are applied in Python.)"""
    conds, params = ["l.corpus = ?"], [cfg.corpus]
    if cfg.languages and len(CORPUS_LANGUAGES[cfg.corpus]) > 1:   # Hebrew and/or Aramaic
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
    return conds, params


# --- caches ---------------------------------------------------------------------
# The BHSA database is read-only, so results that only depend on it (and on a
# deck's settings) are kept while the app runs. Keys include the database file.

_cache: dict[tuple, object] = {}


def _bhsa_file(con: sqlite3.Connection) -> str:
    for _seq, name, path in con.execute("PRAGMA database_list"):
        if name == "bhsa":
            return path
    return ""


def _cached(con: sqlite3.Connection, key: tuple, compute):
    full = (_bhsa_file(con), *key)
    if full not in _cache:
        if len(_cache) > 500:
            _cache.clear()
        _cache[full] = compute()
    return _cache[full]


def passage_nodes(con: sqlite3.Connection, p: Passage) -> tuple[int, int] | None:
    """First and last word node of a passage (None if it has no words)."""
    key = ("passage", p.book, p.chapter_from or 1, p.chapter_to or 999)

    def compute():
        row = con.execute(
            "SELECT MIN(w.node), MAX(w.node) FROM bhsa.verses v "
            "JOIN bhsa.words w ON w.verse_id = v.verse_id "
            "WHERE v.book = ? AND v.chapter BETWEEN ? AND ?", key[1:]).fetchone()
        return (row[0], row[1]) if row[0] is not None else None
    return _cached(con, key, compute)


def _plan_positions(con: sqlite3.Connection, plan_id: str) -> dict[str, int]:
    return _cached(con, ("plan", plan_id), lambda: {r[0]: r[1] for r in con.execute(
        "SELECT lex_id, position FROM bhsa.plan_items WHERE plan_id = ?", (plan_id,))})


def _askable_stems(con: sqlite3.Connection) -> frozenset:
    """(lex_id, stem) pairs with at least one occurrence that can be asked."""
    return _cached(con, ("askable",), lambda: frozenset(
        (r[0], r[1]) for r in con.execute(
            f"SELECT DISTINCT lex_id, stem FROM bhsa.words w WHERE {ASKABLE}")))


def _glossed(con: sqlite3.Connection, gloss_language: str) -> set[str]:
    """Lexemes with a gloss in a language (built in or the user's own)."""
    builtin = _cached(con, ("glossed", gloss_language), lambda: frozenset(
        r[0] for r in con.execute("SELECT DISTINCT lex_id FROM bhsa.glosses "
                                  "WHERE gloss_language = ?", (gloss_language,))))
    own = {r[0] for r in con.execute("SELECT DISTINCT lex_id FROM user_glosses "
                                     "WHERE gloss_language = ?", (gloss_language,))}
    return builtin | own


def _selection_key(cfg: DeckConfig) -> tuple:
    """The settings that decide which cards are in a deck (not the study settings)."""
    return ("deck", cfg.corpus, cfg.plan_id, tuple(cfg.languages or ()),
            tuple(cfg.pos) if cfg.pos is not None else None, cfg.rank_min, cfg.rank_max,
            tuple(cfg.stems) if cfg.stems is not None else None,
            tuple(cfg.tenses) if cfg.tenses is not None else None,
            tuple(cfg.voices) if cfg.voices is not None else None,
            tuple(cfg.moods) if cfg.moods is not None else None, cfg.suffix,
            tuple((p.book, p.chapter_from, p.chapter_to) for p in cfg.passages or ()),
            tuple(cfg.include_lex), tuple(cfg.exclude_lex), cfg.split_stems)


def deck_cards(con: sqlite3.Connection, cfg: DeckConfig) -> list[CardKey]:
    """All card keys of a deck, in the order new cards are introduced.

    Plan decks follow the plan order; filter decks go from the most to the least
    frequent lexeme. With split_stems, a verb's stems follow each other, most
    frequent stem first. Lexemes added by hand (include_lex) are always in the
    deck; lexemes with no askable occurrence never are.
    """
    keys = _cached(con, _selection_key(cfg), lambda: _compute_cards(con, cfg))
    if cfg.gloss_language != "English":
        allowed = _glossed(con, cfg.gloss_language)
        included = set(cfg.include_lex)
        keys = [k for k in keys if k.lex_id in allowed or k.lex_id in included]
    return list(keys)


def _compute_cards(con: sqlite3.Connection, cfg: DeckConfig) -> list[CardKey]:
    lex_conds, lex_params = lexeme_conditions(cfg)
    word_level = (cfg.tenses is not None or cfg.voices is not None or cfg.moods is not None
                  or cfg.suffix != "any" or bool(cfg.passages))
    askable = _askable_stems(con)

    if word_level:
        # Filters on single occurrences: count the matching words.
        occ_conds, occ_params = occurrence_conditions(cfg, con)
        where = " AND ".join(lex_conds + occ_conds + [ASKABLE])
        rows = con.execute(f"""
            SELECT w.lex_id, w.stem, COUNT(*), l.freq
            FROM bhsa.words w JOIN bhsa.lexemes l ON l.lex_id = w.lex_id
            WHERE {where}
            GROUP BY w.lex_id, w.stem""", lex_params + occ_params).fetchall()
    else:
        # Lexeme filters (and stems) only: the per-stem counts are enough.
        conds, params = list(lex_conds), list(lex_params)
        if cfg.stems is not None:
            sql, p = _in("s.stem", cfg.stems)
            conds.append(f"(s.stem = 'NA' OR {sql})")      # the stem filter only applies to verbs
            params += p
        where = " AND ".join(conds) or "1"
        rows = [r for r in con.execute(f"""
            SELECT s.lex_id, s.stem, s.freq, l.freq
            FROM bhsa.lexeme_stems s JOIN bhsa.lexemes l ON l.lex_id = s.lex_id
            WHERE {where}""", params) if (r[0], r[1]) in askable]

    if cfg.include_lex:
        # Words added by hand are in the deck whatever the filters say.
        sql, p = _in("s.lex_id", cfg.include_lex)
        present = {(r[0], r[1]) for r in rows}
        rows += [r for r in con.execute(f"""
            SELECT s.lex_id, s.stem, s.freq, l.freq
            FROM bhsa.lexeme_stems s JOIN bhsa.lexemes l ON l.lex_id = s.lex_id
            WHERE {sql}""", p) if (r[0], r[1]) in askable and (r[0], r[1]) not in present]

    excluded = set(cfg.exclude_lex)
    included = set(cfg.include_lex)
    positions = _plan_positions(con, cfg.plan_id) if cfg.plan_id else None

    grouped: dict[tuple[str, str], list] = {}
    for lex_id, stem, n, lex_freq in rows:
        if lex_id in excluded:
            continue
        if positions is not None and lex_id not in positions and lex_id not in included:
            continue
        card_stem = stem if cfg.split_stems and stem != "NA" else ALL_STEMS
        entry = grouped.setdefault((lex_id, card_stem), [0, lex_freq])
        entry[0] += n

    def order(item):
        (lex_id, _stem), (n, lex_freq) = item
        plan_pos = positions.get(lex_id, 1_000_000_000) if positions is not None else 0
        return (plan_pos, -lex_freq, lex_id, -n)

    return [CardKey(lex_id, stem) for (lex_id, stem), _ in sorted(grouped.items(), key=order)]


def occurrences(con: sqlite3.Connection, cfg: DeckConfig, key: CardKey) -> list[sqlite3.Row]:
    """Occurrences (node, form_utf8) of a card that pass the occurrence filters.

    Only askable occurrences are returned (see ASKABLE). Falls back to all
    askable occurrences of the card when none pass the filters (e.g. for a
    lexeme the user added by hand).
    """
    base = f"SELECT w.node, w.form_utf8 FROM bhsa.words w WHERE w.lex_id = ? AND {ASKABLE}"
    params: list = [key.lex_id]
    if key.stem != ALL_STEMS:
        base += " AND w.stem = ?"
        params.append(key.stem)
    conds, occ_params = occurrence_conditions(cfg, con)
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
        "SELECT p.plan_id, p.corpus, p.name, p.description, COUNT(i.lex_id) AS size "
        "FROM bhsa.plans p JOIN bhsa.plan_items i USING (plan_id) GROUP BY p.plan_id "
        "ORDER BY MIN(p.rowid)").fetchall()


def language_label(con: sqlite3.Connection, cfg: DeckConfig) -> str:
    """The language(s) of a deck's words, e.g. 'Hebrew', 'Hebrew and Aramaic', 'Greek'."""
    available = CORPUS_LANGUAGES.get(cfg.corpus, [])
    if cfg.plan_id:
        in_plan = _cached(con, ("plan languages", cfg.plan_id), lambda: frozenset(
            r[0] for r in con.execute(
                "SELECT DISTINCT l.language FROM bhsa.plan_items p "
                "JOIN bhsa.lexemes l ON l.lex_id = p.lex_id WHERE p.plan_id = ?", (cfg.plan_id,))))
        languages = [lang for lang in available if lang in in_plan]
    elif len(available) > 1:
        languages = [lang for lang in available if lang in (cfg.languages or available)]
    else:
        languages = list(available)
    return " and ".join(languages) or "–"
