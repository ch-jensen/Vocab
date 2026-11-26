"""The user's own glosses: editing, and importing/exporting gloss files.

Gloss files use the layout of the notebook version (e.g. Danish_glosses.csv):
an index column, `lex` (ETCBC transliteration), `default`, and one column per
verbal stem. The gloss language is taken from the file name.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .store import Store

STEM_COLUMNS = ["default", "qal", "nif", "piel", "pual", "hit", "hif", "hof", "hsht", "pasq",
                "etpa", "nit", "hotp", "tif", "htpa", "poal", "poel", "peal", "peil", "pael",
                "haf", "afel", "shaf", "htpe", "htpo", "etpe"]


def set_gloss(store: Store, lex_id: str, gloss_language: str, stem: str, gloss: str) -> None:
    """Set the user's gloss; an empty gloss removes the user's own entry."""
    gloss = gloss.strip()
    if gloss:
        store.con.execute("INSERT OR REPLACE INTO user_glosses VALUES (?, ?, ?, ?)",
                          (lex_id, gloss_language, stem, gloss))
    else:
        store.con.execute("DELETE FROM user_glosses WHERE lex_id = ? AND gloss_language = ? "
                          "AND stem = ?", (lex_id, gloss_language, stem))
    store.con.commit()


def builtin_glosses(store: Store, lex_id: str, gloss_language: str) -> dict[str, str]:
    return {r[0]: r[1] for r in store.con.execute(
        "SELECT stem, gloss FROM bhsa.glosses WHERE lex_id = ? AND gloss_language = ?",
        (lex_id, gloss_language))}


def language_from_filename(path: Path) -> str:
    name = Path(path).stem
    return name[: -len("_glosses")] if name.lower().endswith("_glosses") else name


@dataclass
class GlossImport:
    language: str
    glosses: int
    unknown: int


def import_csv(store: Store, path: Path | str, language: str | None = None) -> GlossImport:
    path = Path(path)
    language = language or language_from_filename(path)
    if not language:
        raise ValueError("Could not tell the gloss language from the file name")
    by_lex: dict[str, list[str]] = {}
    for lex_id, lex in store.con.execute("SELECT lex_id, lex FROM bhsa.lexemes"):
        by_lex.setdefault(lex, []).append(lex_id)
    rows, unknown = [], 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "lex" not in reader.fieldnames:
            raise ValueError("The file has no 'lex' column")
        stems = [c for c in reader.fieldnames if c in STEM_COLUMNS]
        for rec in reader:
            lex = (rec.get("lex") or "").strip()
            if not lex:
                continue
            if lex not in by_lex:
                unknown += 1
                continue
            for stem in stems:
                gloss = (rec.get(stem) or "").strip()
                if gloss:
                    rows += [(lex_id, language, stem, gloss) for lex_id in by_lex[lex]]
    store.con.executemany("INSERT OR REPLACE INTO user_glosses VALUES (?, ?, ?, ?)", rows)
    store.con.commit()
    return GlossImport(language, len(rows), unknown)


def export_csv(store: Store, gloss_language: str, path: Path | str) -> int:
    """Write all glosses in one language (built-in and the user's) as a gloss file."""
    merged: dict[str, dict[str, str]] = {}
    for table in ("bhsa.glosses", "user_glosses"):   # user glosses overwrite built-in ones
        for lex, stem, gloss in store.con.execute(
                f"SELECT l.lex, g.stem, g.gloss FROM {table} g "
                "JOIN bhsa.lexemes l ON l.lex_id = g.lex_id WHERE g.gloss_language = ? "
                "ORDER BY l.rank, l.lex", (gloss_language,)):
            merged.setdefault(lex, {})[stem] = gloss
    used = [c for c in STEM_COLUMNS if any(c in g for g in merged.values())]
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["", "lex", *used])
        for i, (lex, glosses) in enumerate(merged.items()):
            w.writerow([i, lex, *(glosses.get(c, "") for c in used)])
    return len(merged)
