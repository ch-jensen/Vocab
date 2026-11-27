"""Database access: the user's own database with the BHSA database attached.

The user database (review state, review log, decks, settings) is read-write and
lives in the user's profile. The BHSA database built by build_db.py is attached
read-only as schema ``bhsa``, so queries can join cards with lexemes and words.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

USER_SCHEMA_VERSION = 1
BHSA_SCHEMA_VERSION = "1"

# In a PyInstaller build, bundled data files live under sys._MEIPASS.
APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DEFAULT_BHSA_DB = APP_ROOT / "data" / "bhsa_vocab.sqlite"


def user_data_dir() -> Path:
    """Where the user's progress is kept, following each system's convention.

    Windows: %APPDATA%\\Vocab; macOS: ~/Library/Application Support/Vocab;
    Linux: $XDG_DATA_HOME/Vocab or ~/.local/share/Vocab.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "Vocab"


def default_user_db() -> Path:
    return user_data_dir() / "user.sqlite"


USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decks (
    deck_id     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    config      TEXT NOT NULL,          -- DeckConfig as JSON
    created_at  TEXT NOT NULL
);

-- One card per lexeme (stem = '*') or per lexeme + verbal stem.
-- Review state is shared by all decks. Columns mirror fsrs.Card.
-- A lexeme that has never been studied has no row ("new").
CREATE TABLE IF NOT EXISTS cards (
    card_id      INTEGER PRIMARY KEY,
    lex_id       TEXT NOT NULL,
    stem         TEXT NOT NULL,
    state        INTEGER NOT NULL,      -- fsrs.State: 1 learning, 2 review, 3 relearning
    step         INTEGER,
    stability    REAL,
    difficulty   REAL,
    due          TEXT NOT NULL,         -- UTC ISO 8601, millisecond precision
    last_review  TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (lex_id, stem)
);
CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);

CREATE TABLE IF NOT EXISTS reviews (
    review_id     INTEGER PRIMARY KEY,
    card_id       INTEGER NOT NULL REFERENCES cards(card_id),
    deck_id       INTEGER REFERENCES decks(deck_id) ON DELETE SET NULL,
    node          INTEGER,              -- BHSA word node shown
    reviewed_at   TEXT NOT NULL,
    rating        INTEGER NOT NULL,     -- fsrs.Rating 1-4
    duration_ms   INTEGER,
    mode          TEXT NOT NULL,        -- 'typed' | 'self'
    answer        TEXT,
    correct       INTEGER,              -- 1/0 for typed answers, NULL for self-grading
    typo          INTEGER NOT NULL DEFAULT 0,
    state_before  INTEGER NOT NULL      -- 0 = new, otherwise fsrs.State
);
CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_reviews_deck ON reviews(deck_id, reviewed_at);

-- Glosses edited or added by the user; they take precedence over bhsa.glosses.
CREATE TABLE IF NOT EXISTS user_glosses (
    lex_id          TEXT NOT NULL,
    gloss_language  TEXT NOT NULL,
    stem            TEXT NOT NULL,
    gloss           TEXT NOT NULL,
    PRIMARY KEY (lex_id, gloss_language, stem)
);
"""


def ts(moment: datetime) -> str:
    """Datetime as a fixed-width UTC string, so text comparison equals time comparison."""
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


DAY_ROLLOVER_HOUR = 4    # the study day starts at 04:00 local time, as in Anki


def day_start(now: datetime, tz: tzinfo | None = None) -> datetime:
    """Start of the study day containing `now` (04:00 local), in UTC."""
    local = now.astimezone(tz)
    start = local.replace(hour=DAY_ROLLOVER_HOUR, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


def align_learned_due_times(con: sqlite3.Connection, tz: tzinfo | None = None) -> int:
    """Move the due time of every learned word to 04:00 of its study day.

    Learned words are scheduled to a day, as in Anki; earlier versions stored the
    exact time of day. Safe to run again: aligned times stay the same.
    Returns the number of words changed.
    """
    changed = []
    for card_id, due in con.execute("SELECT card_id, due FROM cards WHERE state = 2"):
        aligned = ts(day_start(datetime.fromisoformat(due), tz))
        if aligned != due:
            changed.append((aligned, card_id))
    con.executemany("UPDATE cards SET due = ? WHERE card_id = ?", changed)
    return len(changed)


class Store:
    def __init__(self, user_db: Path | str | None = None, bhsa_db: Path | str | None = None):
        self.user_db = Path(user_db) if user_db else default_user_db()
        self.bhsa_db = Path(bhsa_db) if bhsa_db else DEFAULT_BHSA_DB
        if not self.bhsa_db.exists():
            raise FileNotFoundError(f"BHSA database not found: {self.bhsa_db} (run build_db.py)")
        self.user_db.parent.mkdir(parents=True, exist_ok=True)

        self.con = sqlite3.connect(self.user_db.resolve().as_uri() + "?mode=rwc", uri=True)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.execute("ATTACH DATABASE ? AS bhsa", (self.bhsa_db.resolve().as_uri() + "?mode=ro",))

        version = self.con.execute(
            "SELECT value FROM bhsa.meta WHERE key = 'schema_version'").fetchone()
        if not version or version[0] != BHSA_SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported BHSA database schema: {version and version[0]}")

        self.con.executescript(USER_SCHEMA)
        self.con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)",
                         (str(USER_SCHEMA_VERSION),))
        # Once per database: learned words from earlier versions get 04:00 on their day.
        if self.get_meta("learned_due_at_day_start") is None:
            align_learned_due_times(self.con)
            self.con.execute("INSERT INTO meta VALUES ('learned_due_at_day_start', '1')")
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def read_only_connection(self) -> sqlite3.Connection:
        """A separate read-only connection (with BHSA attached), e.g. for a worker thread."""
        con = sqlite3.connect(self.user_db.resolve().as_uri() + "?mode=ro", uri=True,
                              check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("ATTACH DATABASE ? AS bhsa", (self.bhsa_db.resolve().as_uri() + "?mode=ro",))
        return con

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- settings ----------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self.con.commit()

    # --- BHSA lookups ------------------------------------------------------
    def lexeme(self, lex_id: str) -> sqlite3.Row:
        return self.con.execute("SELECT * FROM bhsa.lexemes WHERE lex_id = ?", (lex_id,)).fetchone()

    def word(self, node: int) -> sqlite3.Row:
        return self.con.execute("SELECT * FROM bhsa.words WHERE node = ?", (node,)).fetchone()

    def clause_words(self, clause_id: int) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT node, form_utf8, trailer_utf8, qere_utf8 FROM bhsa.words "
            "WHERE clause_id = ? ORDER BY node", (clause_id,)).fetchall()

    def reference(self, verse_id: int) -> str:
        r = self.con.execute("SELECT book_en, chapter, verse FROM bhsa.verses WHERE verse_id = ?",
                             (verse_id,)).fetchone()
        return f"{r['book_en'].replace('_', ' ')} {r['chapter']}:{r['verse']}"

    def stem_counts(self, lex_id: str) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.con.execute(
            "SELECT stem, freq FROM bhsa.lexeme_stems WHERE lex_id = ? ORDER BY freq DESC", (lex_id,))]

    def glosses(self, lex_id: str, gloss_language: str) -> dict[str, str]:
        """Glosses by stem ('default', 'qal', ...); the user's own glosses win."""
        out = {r[0]: r[1] for r in self.con.execute(
            "SELECT stem, gloss FROM bhsa.glosses WHERE lex_id = ? AND gloss_language = ?",
            (lex_id, gloss_language))}
        out.update({r[0]: r[1] for r in self.con.execute(
            "SELECT stem, gloss FROM user_glosses WHERE lex_id = ? AND gloss_language = ?",
            (lex_id, gloss_language))})
        return out

    def books(self) -> list[tuple[str, str, int]]:
        """(BHSA name, English name, number of chapters) in canonical order."""
        return [(r[0], r[1].replace("_", " "), r[2]) for r in self.con.execute(
            "SELECT book, book_en, MAX(chapter) FROM bhsa.verses "
            "GROUP BY book_order ORDER BY book_order")]

    def stems(self) -> list[tuple[str, str, int]]:
        """(stem, language, number of occurrences) for all verbal stems."""
        return [tuple(r) for r in self.con.execute(
            "SELECT s.stem, l.language, SUM(s.freq) FROM bhsa.lexeme_stems s "
            "JOIN bhsa.lexemes l USING (lex_id) WHERE s.stem <> 'NA' "
            "GROUP BY s.stem, l.language ORDER BY l.language DESC, SUM(s.freq) DESC")]

    def gloss_languages(self) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT gloss_language FROM bhsa.glosses UNION SELECT gloss_language FROM user_glosses "
            "ORDER BY 1")]
