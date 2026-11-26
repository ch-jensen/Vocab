"""Exporting and importing decks as .vocabdeck files.

A deck file is a small JSON document with the deck's settings (which words,
which forms, study settings) and the user's own glosses for the deck's words in
the deck's gloss language. Learning progress is not included: it is personal,
and it is shared by all of a user's decks.

On import, the user's own glosses are never overwritten; glosses from the file
are only added where the user has none of their own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .decks import Deck, DeckConfig, create_deck, deck_cards, get_deck
from .store import Store, ts

FORMAT = "vocab-deck"
FORMAT_VERSION = 1
EXTENSION = ".vocabdeck"


def export_deck(store: Store, deck: Deck, path: Path | str) -> int:
    """Write a deck file; returns the number of the user's own glosses included."""
    keys = deck_cards(store.con, deck.config)
    lex_ids = sorted({k.lex_id for k in keys})
    glosses = []
    for i in range(0, len(lex_ids), 500):          # stay below SQLite's parameter limit
        chunk = lex_ids[i:i + 500]
        glosses += [{"lex_id": r[0], "stem": r[1], "gloss": r[2]} for r in store.con.execute(
            f"SELECT lex_id, stem, gloss FROM user_glosses WHERE gloss_language = ? "
            f"AND lex_id IN ({','.join('?' * len(chunk))}) ORDER BY lex_id, stem",
            (deck.config.gloss_language, *chunk))]
    data = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "bhsa_version": store.con.execute(
            "SELECT value FROM bhsa.meta WHERE key = 'bhsa_version'").fetchone()[0],
        "exported_at": ts(datetime.now(timezone.utc)),
        "name": deck.name,
        "words": len(keys),
        "config": asdict(deck.config),
        "gloss_language": deck.config.gloss_language,
        "glosses": glosses,
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(glosses)


@dataclass
class DeckImport:
    deck: Deck
    words: int
    glosses_added: int
    glosses_kept: int        # the user already had their own gloss
    renamed: bool
    warnings: list[str]


def read_deck_file(path: Path | str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"The file could not be read as a deck file ({exc}).") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("This is not a Vocab deck file.")
    if int(data.get("format_version", 0)) > FORMAT_VERSION:
        raise ValueError("This deck file was made by a newer version of Vocab. "
                         "Please update the app.")
    if not isinstance(data.get("config"), dict) or not data.get("name"):
        raise ValueError("The deck file is incomplete.")
    return data


def unique_name(store: Store, name: str) -> str:
    if get_deck(store, name) is None:
        return name
    n = 2
    while get_deck(store, f"{name} ({n})") is not None:
        n += 1
    return f"{name} ({n})"


def import_deck(store: Store, path: Path | str) -> DeckImport:
    data = read_deck_file(path)
    try:
        cfg = DeckConfig.from_json(json.dumps(data["config"]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"The deck settings in the file are not valid ({exc}).") from exc

    warnings = []
    ours = store.con.execute("SELECT value FROM bhsa.meta WHERE key = 'bhsa_version'").fetchone()[0]
    if data.get("bhsa_version") and data["bhsa_version"] != ours:
        warnings.append(f"The deck was made with BHSA {data['bhsa_version']}; this app uses "
                        f"BHSA {ours}, so the words may differ slightly.")
    if cfg.plan_id and not store.con.execute(
            "SELECT 1 FROM bhsa.plans WHERE plan_id = ?", (cfg.plan_id,)).fetchone():
        raise ValueError(f"The deck uses a study plan this app doesn't have ({cfg.plan_id}).")
    books = {r[0] for r in store.con.execute("SELECT DISTINCT book FROM bhsa.verses")}
    unknown_books = sorted({p.book for p in cfg.passages or []} - books)
    if unknown_books:
        raise ValueError(f"The deck uses unknown books: {', '.join(unknown_books)}.")

    # Glosses: add the file's glosses where the user has none of their own.
    known_lex = {r[0] for r in store.con.execute("SELECT lex_id FROM bhsa.lexemes")}
    language = data.get("gloss_language") or cfg.gloss_language
    added = kept = 0
    for g in data.get("glosses") or []:
        lex_id, stem, gloss = g.get("lex_id"), g.get("stem"), (g.get("gloss") or "").strip()
        if lex_id not in known_lex or not stem or not gloss:
            continue
        cur = store.con.execute("INSERT OR IGNORE INTO user_glosses VALUES (?, ?, ?, ?)",
                                (lex_id, language, stem, gloss))
        if cur.rowcount:
            added += 1
        else:
            kept += 1
    store.con.commit()

    words = len(deck_cards(store.con, cfg))
    if words == 0:
        warnings.append("No words in this app match the deck's settings.")
    name = unique_name(store, str(data["name"]).strip())
    deck = create_deck(store, name, cfg)
    return DeckImport(deck, words, added, kept, name != str(data["name"]).strip(), warnings)
