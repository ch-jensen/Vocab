"""Build the read-only BHSA vocabulary database used by the desktop app.

This script is run once by the developer (not by end users). It reads the
BHSA through Text-Fabric and writes a single SQLite file, so the packaged app
never needs Text-Fabric, Jupyter or an internet connection.

Usage:
    python build_db.py                       # uses ~/text-fabric-data, BHSA 2021
    python build_db.py --version 2021 --out data/bhsa_vocab.sqlite
    python build_db.py --glosses ../Danish_glosses.csv

Data: BHSA by the ETCBC, CC BY-NC 4.0 (https://github.com/ETCBC/bhsa).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 1

FEATURES = (
    "otype lex lex_utf8 voc_lex_utf8 gloss language sp pdp vs vt ps nu gn st "
    "prs prs_ps prs_nu prs_gn freq_lex rank_lex g_word_utf8 trailer_utf8 "
    "qere_utf8 book book@en chapter verse"
)

LANG_CODE = {"Hebrew": "hbo", "Aramaic": "arc"}

# Values in BHSA that mean "not applicable".
NA = {"NA", "N/A", "absent", "n/a", "unknown", ""}

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per BHSA lexeme. lex_id = '<lang>:<lex>', e.g. 'hbo:>B/'.
-- It is stable across BHSA versions, unlike node numbers.
CREATE TABLE lexemes (
    lex_id        TEXT PRIMARY KEY,
    lex           TEXT NOT NULL,     -- ETCBC transliteration, e.g. '>B/'
    language      TEXT NOT NULL,     -- 'Hebrew' | 'Aramaic'
    lex_utf8      TEXT NOT NULL,     -- consonantal Hebrew
    voc_lex_utf8  TEXT,              -- vocalised dictionary form
    sp            TEXT NOT NULL,     -- part of speech (subs, verb, ...)
    freq          INTEGER NOT NULL,  -- number of occurrences
    rank          INTEGER NOT NULL,  -- BHSA rank_lex (0 = most frequent)
    UNIQUE (language, lex)
);

-- Occurrences per lexeme and verbal stem ('NA' for non-verbs).
CREATE TABLE lexeme_stems (
    lex_id  TEXT NOT NULL REFERENCES lexemes(lex_id),
    stem    TEXT NOT NULL,
    freq    INTEGER NOT NULL,
    PRIMARY KEY (lex_id, stem)
);

CREATE TABLE verses (
    verse_id    INTEGER PRIMARY KEY,  -- BHSA verse node
    book        TEXT NOT NULL,        -- BHSA (Latin) book name, e.g. 'Genesis'
    book_en     TEXT NOT NULL,
    book_order  INTEGER NOT NULL,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL
);

CREATE TABLE clauses (
    clause_id  INTEGER PRIMARY KEY,   -- BHSA clause node
    verse_id   INTEGER NOT NULL REFERENCES verses(verse_id)
);

-- One row per word occurrence (BHSA word node = slot).
-- The clause text is rebuilt with:
--   SELECT form_utf8, trailer_utf8 FROM words WHERE clause_id = ? ORDER BY node
CREATE TABLE words (
    node          INTEGER PRIMARY KEY,
    lex_id        TEXT NOT NULL REFERENCES lexemes(lex_id),
    form_utf8     TEXT NOT NULL,      -- pointed form as written (ketiv)
    trailer_utf8  TEXT NOT NULL,      -- space / maqaf / sof pasuq after the word
    qere_utf8     TEXT,               -- qere reading, if any
    sp            TEXT NOT NULL,      -- part of speech of this occurrence
    stem          TEXT NOT NULL,      -- verbal stem (vs) or 'NA'
    tense         TEXT NOT NULL,      -- verbal tense (vt) or 'NA'
    person        TEXT NOT NULL,
    number        TEXT NOT NULL,
    gender        TEXT NOT NULL,
    state         TEXT NOT NULL,
    has_suffix    INTEGER NOT NULL,   -- pronominal suffix present (0/1)
    sfx_person    TEXT NOT NULL,
    sfx_number    TEXT NOT NULL,
    sfx_gender    TEXT NOT NULL,
    clause_id     INTEGER NOT NULL REFERENCES clauses(clause_id),
    verse_id      INTEGER NOT NULL REFERENCES verses(verse_id)
);

-- Glosses per gloss language, lexeme and stem.
-- stem = 'default' for the general gloss; otherwise a BHSA stem such as 'piel'.
CREATE TABLE glosses (
    lex_id          TEXT NOT NULL REFERENCES lexemes(lex_id),
    gloss_language  TEXT NOT NULL,
    stem            TEXT NOT NULL,
    gloss           TEXT NOT NULL,
    PRIMARY KEY (lex_id, gloss_language, stem)
);

-- Predefined study plans: lexemes in the order they are introduced.
CREATE TABLE plans (
    plan_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL
);

CREATE TABLE plan_items (
    plan_id   TEXT NOT NULL REFERENCES plans(plan_id),
    position  INTEGER NOT NULL,
    lex_id    TEXT NOT NULL REFERENCES lexemes(lex_id),
    PRIMARY KEY (plan_id, position)
);
"""

INDEXES = """
CREATE INDEX idx_words_lex     ON words(lex_id);
CREATE INDEX idx_words_clause  ON words(clause_id);
CREATE INDEX idx_words_verse   ON words(verse_id);
CREATE INDEX idx_words_filter  ON words(lex_id, stem, tense, has_suffix);
CREATE INDEX idx_verses_book   ON verses(book_order, chapter, verse);
CREATE INDEX idx_lexemes_rank  ON lexemes(language, rank);
CREATE INDEX idx_plan_lex      ON plan_items(lex_id);
"""


def clean(value) -> str:
    """Normalise BHSA 'not applicable' values to 'NA'."""
    if value is None:
        return "NA"
    value = str(value)
    return "NA" if value in NA else value


def load_bhsa(tf_location: Path):
    from tf.fabric import Fabric

    if not tf_location.is_dir():
        sys.exit(f"BHSA data not found at {tf_location}. "
                 "Download it once with: from tf.app import use; use('ETCBC/bhsa')")
    TF = Fabric(locations=str(tf_location), silent="deep")
    api = TF.load(FEATURES, silent="deep")
    if not api:
        sys.exit("Text-Fabric could not load the BHSA features.")
    return api


def build(api, out: Path, version: str, gloss_files: list[Path]) -> None:
    F, L, Fs = api.F, api.L, api.Fs
    book_en = Fs("book@en")

    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)

    # --- lexemes -----------------------------------------------------------
    t0 = time.time()
    lex_node_to_id: dict[int, str] = {}
    lex_rows = []
    for lx in F.otype.s("lex"):
        language = F.language.v(lx)
        lex = F.lex.v(lx)
        lex_id = f"{LANG_CODE[language]}:{lex}"
        lex_node_to_id[lx] = lex_id
        lex_rows.append((
            lex_id, lex, language, F.lex_utf8.v(lx), F.voc_lex_utf8.v(lx),
            F.sp.v(lx), F.freq_lex.v(lx), F.rank_lex.v(lx),
        ))
    con.executemany("INSERT INTO lexemes VALUES (?,?,?,?,?,?,?,?)", lex_rows)
    print(f"lexemes: {len(lex_rows)} ({time.time() - t0:.1f}s)")

    # --- verses ------------------------------------------------------------
    verse_rows = []
    for order, bk in enumerate(F.otype.s("book"), start=1):
        name = F.book.v(bk)
        name_en = book_en.v(bk) or name
        for vs in L.d(bk, "verse"):
            verse_rows.append((vs, name, name_en, order, F.chapter.v(vs), F.verse.v(vs)))
    con.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?)", verse_rows)
    print(f"verses: {len(verse_rows)}")

    # --- clauses -----------------------------------------------------------
    clause_rows = []
    for cl in F.otype.s("clause"):
        verse = L.u(cl, "verse")
        # A clause can in principle span a verse boundary; anchor it to the
        # verse of its first word.
        if not verse:
            verse = L.u(L.d(cl, "word")[0], "verse")
        clause_rows.append((cl, verse[0]))
    con.executemany("INSERT INTO clauses VALUES (?,?)", clause_rows)
    print(f"clauses: {len(clause_rows)}")

    # --- words -------------------------------------------------------------
    t0 = time.time()
    word_rows = []
    stem_counts: dict[tuple[str, str], int] = {}
    for w in F.otype.s("word"):
        lex_id = lex_node_to_id[L.u(w, "lex")[0]]
        stem = clean(F.vs.v(w))
        prs = F.prs.v(w)
        has_suffix = int(prs not in NA)
        clause = L.u(w, "clause")
        verse = L.u(w, "verse")
        qere = F.qere_utf8.v(w)
        word_rows.append((
            w, lex_id, F.g_word_utf8.v(w) or "",
            F.trailer_utf8.v(w) or "",
            qere or None,
            F.sp.v(w), stem, clean(F.vt.v(w)),
            clean(F.ps.v(w)), clean(F.nu.v(w)), clean(F.gn.v(w)), clean(F.st.v(w)),
            has_suffix,
            clean(F.prs_ps.v(w)), clean(F.prs_nu.v(w)), clean(F.prs_gn.v(w)),
            clause[0], verse[0],
        ))
        key = (lex_id, stem)
        stem_counts[key] = stem_counts.get(key, 0) + 1
    con.executemany(
        "INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", word_rows)
    con.executemany(
        "INSERT INTO lexeme_stems VALUES (?,?,?)",
        [(lex_id, stem, n) for (lex_id, stem), n in sorted(stem_counts.items())])
    print(f"words: {len(word_rows)} ({time.time() - t0:.1f}s)")

    # --- glosses -----------------------------------------------------------
    english = [(lex_node_to_id[lx], "English", "default", F.gloss.v(lx))
               for lx in F.otype.s("lex") if F.gloss.v(lx)]
    con.executemany("INSERT INTO glosses VALUES (?,?,?,?)", english)
    print(f"glosses English: {len(english)}")
    for path in gloss_files:
        import_gloss_csv(con, path)

    # --- plans -------------------------------------------------------------
    build_plans(con)

    # --- meta --------------------------------------------------------------
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "bhsa_version": version,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "BHSA by the ETCBC, https://github.com/ETCBC/bhsa",
        "license": "CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)",
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())

    con.executescript(INDEXES)
    con.commit()
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def import_gloss_csv(con: sqlite3.Connection, path: Path) -> None:
    """Import a '<Language>_glosses.csv' file in the layout of Danish_glosses.csv.

    Columns: (index), lex, default, qal, nif, piel, ... One row per lex; empty
    cells mean no gloss. The file has no language column, so a lex found in
    both Hebrew and Aramaic gets the gloss for both.
    """
    gloss_language = path.name.split("_glosses")[0]
    by_lex: dict[str, list[str]] = {}
    for lex_id, lex in con.execute("SELECT lex_id, lex FROM lexemes"):
        by_lex.setdefault(lex, []).append(lex_id)

    rows, unknown = [], []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        stem_cols = [c for c in reader.fieldnames if c and c != "lex"]
        for rec in reader:
            lex = (rec.get("lex") or "").strip()
            if not lex:
                continue
            if lex not in by_lex:
                unknown.append(lex)
                continue
            for col in stem_cols:
                gloss = (rec.get(col) or "").strip()
                if gloss:
                    for lex_id in by_lex[lex]:
                        rows.append((lex_id, gloss_language, col, gloss))
    con.executemany("INSERT OR REPLACE INTO glosses VALUES (?,?,?,?)", rows)
    print(f"glosses {gloss_language}: {len(rows)} from {path.name}"
          + (f" ({len(unknown)} unknown lexemes skipped)" if unknown else ""))


def build_plans(con: sqlite3.Connection) -> None:
    plans = [
        ("hebrew-frequency", "Biblical Hebrew by frequency",
         "All Hebrew lexemes from the most to the least frequent.",
         "language = 'Hebrew'"),
        ("hebrew-frequency-no-names", "Biblical Hebrew by frequency (no proper nouns)",
         "Hebrew lexemes from the most to the least frequent, without proper nouns.",
         "language = 'Hebrew' AND sp <> 'nmpr'"),
        ("aramaic-frequency", "Biblical Aramaic by frequency",
         "All Aramaic lexemes from the most to the least frequent.",
         "language = 'Aramaic'"),
    ]
    for plan_id, name, desc, where in plans:
        con.execute("INSERT INTO plans VALUES (?,?,?)", (plan_id, name, desc))
        lex_ids = [r[0] for r in con.execute(
            f"SELECT lex_id FROM lexemes WHERE {where} ORDER BY freq DESC, rank, lex")]
        con.executemany("INSERT INTO plan_items VALUES (?,?,?)",
                        [(plan_id, i, lex_id) for i, lex_id in enumerate(lex_ids, start=1)])
        print(f"plan {plan_id}: {len(lex_ids)} lexemes")


def main(argv=None) -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default="2021", help="BHSA version (default 2021)")
    ap.add_argument("--tf-data", type=Path,
                    default=Path(os.path.expanduser("~/text-fabric-data/github/ETCBC/bhsa/tf")),
                    help="folder that contains the BHSA version folders")
    ap.add_argument("--out", type=Path, default=here / "data" / "bhsa_vocab.sqlite")
    ap.add_argument("--glosses", type=Path, nargs="*",
                    default=sorted(here.parent.glob("*_glosses.csv")),
                    help="extra gloss CSV files (default: *_glosses.csv in the repo root)")
    args = ap.parse_args(argv)

    t0 = time.time()
    api = load_bhsa(args.tf_data / args.version)
    print(f"BHSA {args.version} loaded ({time.time() - t0:.1f}s)")
    build(api, args.out, args.version, args.glosses)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
