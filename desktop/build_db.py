"""Build the read-only vocabulary database used by the desktop app.

This script is run once by the developer (not by end users). It reads the
corpora through Text-Fabric and writes a single SQLite file, so the packaged app
never needs Text-Fabric, Jupyter or an internet connection.

Corpora:
  * bhsa   the Hebrew Bible (BHSA 2021, ETCBC), CC BY-NC 4.0
  * n1904  the Greek New Testament (Nestle 1904, Text-Fabric N1904 by CBLC/ETCBC,
           MIT; based on MACULA Greek, CC BY 4.0), with glosses from Bible Online
           Learner (Ezer IT Consulting), used with permission

Usage:
    python build_db.py                       # both corpora, from ~/text-fabric-data
    python build_db.py --no-n1904            # Hebrew Bible only
    python build_db.py --glosses ../Danish_glosses.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA_VERSION = 2

BHSA_FEATURES = (
    "otype lex lex_utf8 voc_lex_utf8 gloss language sp pdp vs vt ps nu gn st "
    "prs prs_ps prs_nu prs_gn freq_lex rank_lex g_word_utf8 trailer_utf8 "
    "qere_utf8 book book@en chapter verse"
)
N1904_FEATURES = (
    "otype lemma strong gloss sp tense voice mood case person number gender "
    "text after book chapter verse"
)

LANG_CODE = {"Hebrew": "hbo", "Aramaic": "arc", "Greek": "grc"}

# Greek NT nodes are stored after the Hebrew Bible's, so ids never collide.
N1904_OFFSET = 10_000_000
N1904_BOOK_ORDER = 100            # Greek books get book_order 101, 102, ...

# Gloss files from Bible Online Learner: language code -> gloss language name.
BIBLEOL_LANGUAGES = {"en": "English", "da": "Danish", "nl": "Dutch", "pt": "Portuguese",
                     "sw": "Swahili", "es": "Spanish"}

# Values in BHSA that mean "not applicable".
NA = {"NA", "N/A", "absent", "n/a", "unknown", ""}

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per lexeme. lex_id = '<lang>:<lex>', e.g. 'hbo:>B/' or 'grc:λόγος'.
-- It is stable across versions of the data, unlike node numbers.
CREATE TABLE lexemes (
    lex_id        TEXT PRIMARY KEY,
    corpus        TEXT NOT NULL,     -- 'bhsa' | 'n1904'
    lex           TEXT NOT NULL,     -- ETCBC transliteration ('>B/') or Greek lemma
    language      TEXT NOT NULL,     -- 'Hebrew' | 'Aramaic' | 'Greek'
    lex_utf8      TEXT NOT NULL,     -- consonantal Hebrew, or the Greek lemma
    voc_lex_utf8  TEXT,              -- vocalised dictionary form, or the Greek lemma
    sp            TEXT NOT NULL,     -- part of speech (subs, verb, nmpr, ...)
    freq          INTEGER NOT NULL,  -- number of occurrences
    rank          INTEGER NOT NULL,  -- frequency rank within the language (0 = most frequent)
    UNIQUE (language, lex)
);

-- Occurrences per lexeme and verbal stem ('NA' for non-verbs and for Greek).
CREATE TABLE lexeme_stems (
    lex_id  TEXT NOT NULL REFERENCES lexemes(lex_id),
    stem    TEXT NOT NULL,
    freq    INTEGER NOT NULL,
    PRIMARY KEY (lex_id, stem)
);

CREATE TABLE verses (
    verse_id    INTEGER PRIMARY KEY,  -- verse node (Greek: + N1904_OFFSET)
    corpus      TEXT NOT NULL,
    book        TEXT NOT NULL,        -- book name in the source, e.g. 'Genesis', 'I_Corinthians'
    book_en     TEXT NOT NULL,
    book_order  INTEGER NOT NULL,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL
);

-- Hebrew: BHSA clauses. Greek: sentences (the context shown is in words.ctx_from/ctx_to).
CREATE TABLE clauses (
    clause_id  INTEGER PRIMARY KEY,
    verse_id   INTEGER NOT NULL REFERENCES verses(verse_id)
);

-- One row per word occurrence. Words are numbered in canonical order.
-- The context shown with a word is the words with the same clause_id (Hebrew),
-- or the words with node BETWEEN ctx_from AND ctx_to (Greek).
CREATE TABLE words (
    node          INTEGER PRIMARY KEY,
    lex_id        TEXT NOT NULL REFERENCES lexemes(lex_id),
    form_utf8     TEXT NOT NULL,      -- the word as written (Hebrew: ketiv)
    trailer_utf8  TEXT NOT NULL,      -- space / maqaf / punctuation after the word
    qere_utf8     TEXT,               -- qere reading, if any (Hebrew)
    sp            TEXT NOT NULL,      -- part of speech of this occurrence
    stem          TEXT NOT NULL,      -- Hebrew verbal stem (vs) or 'NA'
    tense         TEXT NOT NULL,      -- verbal tense or 'NA'
    person        TEXT NOT NULL,
    number        TEXT NOT NULL,
    gender        TEXT NOT NULL,
    state         TEXT NOT NULL,      -- Hebrew state or 'NA'
    has_suffix    INTEGER NOT NULL,   -- Hebrew pronominal suffix present (0/1)
    sfx_person    TEXT NOT NULL,
    sfx_number    TEXT NOT NULL,
    sfx_gender    TEXT NOT NULL,
    voice         TEXT NOT NULL,      -- Greek voice or 'NA'
    mood          TEXT NOT NULL,      -- Greek mood or 'NA'
    noun_case     TEXT NOT NULL,      -- Greek case or 'NA'
    clause_id     INTEGER NOT NULL REFERENCES clauses(clause_id),
    verse_id      INTEGER NOT NULL REFERENCES verses(verse_id),
    ctx_from      INTEGER,            -- Greek: first and last node of the context shown
    ctx_to        INTEGER
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
    corpus       TEXT NOT NULL,
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

WORD_COLUMNS = ("node, lex_id, form_utf8, trailer_utf8, qere_utf8, sp, stem, tense, person, number, "
                "gender, state, has_suffix, sfx_person, sfx_number, sfx_gender, voice, mood, "
                "noun_case, clause_id, verse_id, ctx_from, ctx_to")


def clean(value) -> str:
    """Normalise 'not applicable' values to 'NA'."""
    if value is None:
        return "NA"
    value = str(value)
    return "NA" if value in NA else value


def nfc(text: str | None) -> str:
    return unicodedata.normalize("NFC", text or "")


def load_tf(location: Path, features: str, name: str, how_to: str):
    from tf.fabric import Fabric

    if not location.is_dir():
        sys.exit(f"{name} data not found at {location}. Download it once with: {how_to}")
    TF = Fabric(locations=str(location), silent="deep")
    api = TF.load(features, silent="deep")
    if not api:
        sys.exit(f"Text-Fabric could not load the {name} features.")
    return api


def insert_words(con: sqlite3.Connection, rows: list[tuple]) -> None:
    marks = ",".join("?" * len(WORD_COLUMNS.split(",")))
    con.executemany(f"INSERT INTO words ({WORD_COLUMNS}) VALUES ({marks})", rows)


# --- Hebrew Bible ----------------------------------------------------------------

def add_bhsa(con: sqlite3.Connection, api, gloss_files: list[Path]) -> None:
    F, L, Fs = api.F, api.L, api.Fs
    book_en = Fs("book@en")

    t0 = time.time()
    lex_node_to_id: dict[int, str] = {}
    lex_rows = []
    for lx in F.otype.s("lex"):
        language = F.language.v(lx)
        lex = F.lex.v(lx)
        lex_id = f"{LANG_CODE[language]}:{lex}"
        lex_node_to_id[lx] = lex_id
        lex_rows.append((lex_id, "bhsa", lex, language, F.lex_utf8.v(lx), F.voc_lex_utf8.v(lx),
                         F.sp.v(lx), F.freq_lex.v(lx), F.rank_lex.v(lx)))
    con.executemany("INSERT INTO lexemes (lex_id, corpus, lex, language, lex_utf8, voc_lex_utf8, "
                    "sp, freq, rank) VALUES (?,?,?,?,?,?,?,?,?)", lex_rows)
    print(f"BHSA lexemes: {len(lex_rows)} ({time.time() - t0:.1f}s)")

    verse_rows = []
    for order, bk in enumerate(F.otype.s("book"), start=1):
        name = F.book.v(bk)
        name_en = book_en.v(bk) or name
        for vs in L.d(bk, "verse"):
            verse_rows.append((vs, "bhsa", name, name_en, order, F.chapter.v(vs), F.verse.v(vs)))
    con.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?)", verse_rows)
    print(f"BHSA verses: {len(verse_rows)}")

    clause_rows = []
    for cl in F.otype.s("clause"):
        verse = L.u(cl, "verse")
        if not verse:           # anchor a clause spanning verses to its first word's verse
            verse = L.u(L.d(cl, "word")[0], "verse")
        clause_rows.append((cl, verse[0]))
    con.executemany("INSERT INTO clauses VALUES (?,?)", clause_rows)
    print(f"BHSA clauses: {len(clause_rows)}")

    t0 = time.time()
    word_rows = []
    stem_counts: Counter = Counter()
    for w in F.otype.s("word"):
        lex_id = lex_node_to_id[L.u(w, "lex")[0]]
        stem = clean(F.vs.v(w))
        qere = F.qere_utf8.v(w)
        word_rows.append((
            w, lex_id, F.g_word_utf8.v(w) or "", F.trailer_utf8.v(w) or "", qere or None,
            F.sp.v(w), stem, clean(F.vt.v(w)),
            clean(F.ps.v(w)), clean(F.nu.v(w)), clean(F.gn.v(w)), clean(F.st.v(w)),
            int(F.prs.v(w) not in NA),
            clean(F.prs_ps.v(w)), clean(F.prs_nu.v(w)), clean(F.prs_gn.v(w)),
            "NA", "NA", "NA",
            L.u(w, "clause")[0], L.u(w, "verse")[0], None, None,
        ))
        stem_counts[(lex_id, stem)] += 1
    insert_words(con, word_rows)
    con.executemany("INSERT INTO lexeme_stems VALUES (?,?,?)",
                    [(lex_id, stem, n) for (lex_id, stem), n in sorted(stem_counts.items())])
    print(f"BHSA words: {len(word_rows)} ({time.time() - t0:.1f}s)")

    english = [(lex_node_to_id[lx], "English", "default", F.gloss.v(lx))
               for lx in F.otype.s("lex") if F.gloss.v(lx)]
    con.executemany("INSERT INTO glosses VALUES (?,?,?,?)", english)
    print(f"BHSA glosses English: {len(english)}")
    for path in gloss_files:
        import_gloss_csv(con, path)


def import_gloss_csv(con: sqlite3.Connection, path: Path) -> None:
    """Import a '<Language>_glosses.csv' file (Hebrew/Aramaic) in the layout of Danish_glosses.csv.

    Columns: (index), lex, default, qal, nif, piel, ... One row per lex; empty
    cells mean no gloss. The file has no language column, so a lex found in
    both Hebrew and Aramaic gets the gloss for both.
    """
    gloss_language = path.name.split("_glosses")[0]
    by_lex: dict[str, list[str]] = {}
    for lex_id, lex in con.execute("SELECT lex_id, lex FROM lexemes WHERE corpus = 'bhsa'"):
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
    print(f"BHSA glosses {gloss_language}: {len(rows)} from {path.name}"
          + (f" ({len(unknown)} unknown lexemes skipped)" if unknown else ""))


# --- Greek New Testament -------------------------------------------------------------

def book_name_en(name: str) -> str:
    """'I_Corinthians' -> '1 Corinthians'."""
    for roman, digit in (("III_", "3 "), ("II_", "2 "), ("I_", "1 ")):
        if name.startswith(roman):
            return digit + name[len(roman):].replace("_", " ")
    return name.replace("_", " ")


CTX_MIN, CTX_MAX = 4, 30     # words in the context shown with a Greek word


def greek_context(L, F, w: int, clause_words: dict[int, tuple[int, int, int]]) -> tuple[int, int]:
    """First and last word of the context shown with word w.

    The smallest clause around w with CTX_MIN..CTX_MAX words; otherwise the
    sentence if it is short enough; otherwise a window of the sentence around w.
    """
    best = None
    for cl in L.u(w, "clause"):
        size, first, last = clause_words[cl]
        if CTX_MIN <= size <= CTX_MAX and (best is None or size < best[0]):
            best = (size, first, last)
    if best:
        return best[1], best[2]
    sentence = L.u(w, "sentence")
    if sentence:
        words = L.d(sentence[0], "word")
        if len(words) <= CTX_MAX:
            return words[0], words[-1]
        i = words.index(w)
        half = CTX_MAX // 2
        lo = max(0, min(i - half, len(words) - CTX_MAX))
        return words[lo], words[min(lo + CTX_MAX - 1, len(words) - 1)]
    return w, w


def _lexeme_key(lexeme: str) -> str:
    """BibleOL lexeme -> comparable lemma ('ἄπειμι (I)' -> 'ἄπειμι')."""
    return nfc(re.sub(r"\s*\([IVX]+\)\s*$", "", lexeme.strip()))


def load_bibleol_glosses(folder: Path) -> dict[str, dict[int, list[tuple[str, str]]]]:
    """language name -> Strong's number -> [(lexeme, gloss)]"""
    out: dict[str, dict[int, list[tuple[str, str]]]] = {}
    for code, language in BIBLEOL_LANGUAGES.items():
        path = folder / f"greek_{code}.csv"
        if not path.exists():
            print(f"  (no {path.name}; {language} glosses skipped)")
            continue
        by_strong: dict[int, list[tuple[str, str]]] = defaultdict(list)
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for rec in csv.DictReader(fh):
                gloss = (rec.get("Gloss") or "").strip()
                try:
                    strong = int(rec["Strong's number"])
                except (KeyError, TypeError, ValueError):
                    continue
                if gloss:
                    by_strong[strong].append((_lexeme_key(rec.get("Lexeme") or ""), gloss))
        out[language] = by_strong
    return out


def pick_gloss(lemma: str, strongs: Counter, by_strong: dict[int, list[tuple[str, str]]]) -> str | None:
    """The gloss for a lemma: from its most common Strong's number, preferring the
    entry whose lexeme is the lemma itself (some numbers are shared by several lexemes)."""
    for strong, _n in strongs.most_common():
        entries = by_strong.get(strong)
        if not entries:
            continue
        for lexeme, gloss in entries:
            if lexeme == lemma:
                return gloss
        if len(entries) == 1:
            return entries[0][1]
    for strong, _n in strongs.most_common():   # shared number, no exact lemma: take the first
        if by_strong.get(strong):
            return by_strong[strong][0][1]
    return None


def add_n1904(con: sqlite3.Connection, api, gloss_folder: Path) -> None:
    F, L = api.F, api.L
    t0 = time.time()
    words = list(F.otype.s("word"))

    # Lexemes: one per lemma (NFC). Proper nouns (capitalised nouns) get sp 'nmpr', as in the BHSA.
    def word_sp(w: int) -> str:
        sp = F.sp.v(w) or "NA"
        lemma = nfc(F.lemma.v(w))
        if sp == "subs" and lemma[:1].isupper():
            return "nmpr"
        return sp

    lemma_of = {w: nfc(F.lemma.v(w)) for w in words}
    freq = Counter(lemma_of.values())
    sps: dict[str, Counter] = defaultdict(Counter)
    strongs: dict[str, Counter] = defaultdict(Counter)
    berean: dict[str, Counter] = defaultdict(Counter)
    for w in words:
        lemma = lemma_of[w]
        sps[lemma][word_sp(w)] += 1
        strongs[lemma][F.strong.v(w)] += 1
        if F.gloss.v(w):
            berean[lemma][F.gloss.v(w).strip()] += 1
    ranked = sorted(freq, key=lambda lem: (-freq[lem], lem))
    rank = {lem: i for i, lem in enumerate(ranked)}
    lex_rows = [(f"grc:{lem}", "n1904", lem, "Greek", lem, lem, sps[lem].most_common(1)[0][0],
                 freq[lem], rank[lem]) for lem in ranked]
    con.executemany("INSERT INTO lexemes (lex_id, corpus, lex, language, lex_utf8, voc_lex_utf8, "
                    "sp, freq, rank) VALUES (?,?,?,?,?,?,?,?,?)", lex_rows)
    con.executemany("INSERT INTO lexeme_stems VALUES (?,?,?)",
                    [(f"grc:{lem}", "NA", freq[lem]) for lem in ranked])
    print(f"N1904 lexemes: {len(lex_rows)}")

    verse_rows = []
    for order, bk in enumerate(F.otype.s("book"), start=N1904_BOOK_ORDER + 1):
        name = F.book.v(bk)
        for vs in L.d(bk, "verse"):
            verse_rows.append((N1904_OFFSET + vs, "n1904", name, book_name_en(name), order,
                               F.chapter.v(vs), F.verse.v(vs)))
    con.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?)", verse_rows)
    print(f"N1904 verses: {len(verse_rows)}")

    # Sentences serve as the 'clauses' of the Greek words (every word is in exactly one).
    clause_rows = []
    for s in F.otype.s("sentence"):
        clause_rows.append((N1904_OFFSET + s, N1904_OFFSET + L.u(L.d(s, "word")[0], "verse")[0]))
    con.executemany("INSERT INTO clauses VALUES (?,?)", clause_rows)

    clause_words = {}
    for cl in F.otype.s("clause"):
        ws = L.d(cl, "word")
        clause_words[cl] = (len(ws), ws[0], ws[-1])

    def na(v) -> str:
        return v if v else "NA"

    word_rows = []
    for w in words:
        first, last = greek_context(L, F, w, clause_words)
        sentence = L.u(w, "sentence")[0]
        word_rows.append((
            N1904_OFFSET + w, f"grc:{lemma_of[w]}", nfc(F.text.v(w)), F.after.v(w) or " ", None,
            word_sp(w), "NA", na(F.tense.v(w)),
            na(F.person.v(w)), na(F.number.v(w)), na(F.gender.v(w)), "NA",
            0, "NA", "NA", "NA",
            na(F.voice.v(w)), na(F.mood.v(w)), na(F.case.v(w)),
            N1904_OFFSET + sentence, N1904_OFFSET + L.u(w, "verse")[0],
            N1904_OFFSET + first, N1904_OFFSET + last,
        ))
    insert_words(con, word_rows)
    print(f"N1904 words: {len(word_rows)} ({time.time() - t0:.1f}s)")

    # Glosses: Bible Online Learner (by Strong's number); English falls back to the
    # Berean interlinear gloss in N1904 (public domain) where BibleOL has none.
    bibleol = load_bibleol_glosses(gloss_folder)
    for language, by_strong in bibleol.items():
        rows, fallback = [], 0
        for lem in ranked:
            gloss = pick_gloss(lem, strongs[lem], by_strong)
            if gloss is None and language == "English" and berean[lem]:
                gloss = berean[lem].most_common(1)[0][0]
                fallback += 1
            if gloss:
                rows.append((f"grc:{lem}", language, "default", gloss))
        con.executemany("INSERT INTO glosses VALUES (?,?,?,?)", rows)
        covered = sum(freq[r[0][4:]] for r in rows)
        print(f"N1904 glosses {language}: {len(rows)} of {len(ranked)} lemmas, "
              f"{100 * covered / len(words):.1f}% of the words"
              + (f" ({fallback} from the Berean gloss)" if fallback else ""))


def apply_corrections(con: sqlite3.Connection, path: Path) -> None:
    """Apply sources/gloss_corrections.csv: our corrections to glosses from the sources.

    Columns: lex_id, gloss_language, stem, gloss, note. Each correction replaces
    the gloss from the source; a lexeme that is not in the database is an error.
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        lex_id = unicodedata.normalize("NFC", r["lex_id"].strip())
        if not con.execute("SELECT 1 FROM lexemes WHERE lex_id = ?", (lex_id,)).fetchone():
            if lex_id.startswith("grc:") and not con.execute(
                    "SELECT 1 FROM lexemes WHERE corpus = 'n1904'").fetchone():
                continue                     # Greek NT not built (--no-n1904)
            sys.exit(f"{path.name}: unknown lexeme {lex_id!r}")
        con.execute("INSERT OR REPLACE INTO glosses VALUES (?,?,?,?)",
                    (lex_id, r["gloss_language"].strip(), r["stem"].strip() or "default",
                     r["gloss"].strip()))
    print(f"gloss corrections: {len(rows)} from {path.name}")


# --- plans and finishing -------------------------------------------------------------

def build_plans(con: sqlite3.Connection) -> None:
    plans = [
        ("hebrew-frequency", "bhsa", "Biblical Hebrew by frequency",
         "All Hebrew lexemes from the most to the least frequent.",
         "language = 'Hebrew'"),
        ("hebrew-frequency-no-names", "bhsa", "Biblical Hebrew by frequency (no proper nouns)",
         "Hebrew lexemes from the most to the least frequent, without proper nouns.",
         "language = 'Hebrew' AND sp <> 'nmpr'"),
        ("aramaic-frequency", "bhsa", "Biblical Aramaic by frequency",
         "All Aramaic lexemes from the most to the least frequent.",
         "language = 'Aramaic'"),
        ("greek-frequency", "n1904", "New Testament Greek by frequency",
         "All Greek lexemes of the New Testament from the most to the least frequent.",
         "language = 'Greek'"),
        ("greek-frequency-no-names", "n1904", "New Testament Greek by frequency (no proper nouns)",
         "Greek lexemes from the most to the least frequent, without proper nouns.",
         "language = 'Greek' AND sp <> 'nmpr'"),
    ]
    for plan_id, corpus, name, desc, where in plans:
        lex_ids = [r[0] for r in con.execute(
            f"SELECT lex_id FROM lexemes WHERE {where} ORDER BY freq DESC, rank, lex")]
        if not lex_ids:
            continue
        con.execute("INSERT INTO plans VALUES (?,?,?,?)", (plan_id, corpus, name, desc))
        con.executemany("INSERT INTO plan_items VALUES (?,?,?)",
                        [(plan_id, i, lex_id) for i, lex_id in enumerate(lex_ids, start=1)])
        print(f"plan {plan_id}: {len(lex_ids)} lexemes")


def main(argv=None) -> None:
    here = Path(__file__).resolve().parent
    tf_data = Path(os.path.expanduser("~/text-fabric-data/github"))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default="2021", help="BHSA version (default 2021)")
    ap.add_argument("--tf-data", type=Path, default=tf_data / "ETCBC" / "bhsa" / "tf",
                    help="folder that contains the BHSA version folders")
    ap.add_argument("--n1904-version", default="1.0.0")
    ap.add_argument("--n1904-data", type=Path, default=tf_data / "CenterBLC" / "N1904" / "tf",
                    help="folder that contains the N1904 version folders")
    ap.add_argument("--no-n1904", action="store_true", help="leave out the Greek New Testament")
    ap.add_argument("--bibleol", type=Path, default=here / "sources" / "bibleol",
                    help="folder with Bible Online Learner's greek_<lang>.csv gloss files")
    ap.add_argument("--corrections", type=Path, default=here / "sources" / "gloss_corrections.csv",
                    help="our corrections to glosses from the sources")
    ap.add_argument("--out", type=Path, default=here / "data" / "bhsa_vocab.sqlite")
    ap.add_argument("--glosses", type=Path, nargs="*",
                    default=sorted(here.parent.glob("*_glosses.csv")),
                    help="extra Hebrew gloss CSV files (default: *_glosses.csv in the repo root)")
    args = ap.parse_args(argv)

    t0 = time.time()
    if args.out.exists():
        args.out.unlink()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.out)
    con.executescript(SCHEMA)

    bhsa = load_tf(args.tf_data / args.version, BHSA_FEATURES, "BHSA",
                   "from tf.app import use; use('ETCBC/bhsa')")
    print(f"BHSA {args.version} loaded ({time.time() - t0:.1f}s)")
    add_bhsa(con, bhsa, args.glosses)
    corpora = {"bhsa": args.version}

    if not args.no_n1904:
        n1904 = load_tf(args.n1904_data / args.n1904_version, N1904_FEATURES, "N1904",
                        "from tf.app import use; use('CenterBLC/N1904')")
        print(f"N1904 {args.n1904_version} loaded ({time.time() - t0:.1f}s)")
        add_n1904(con, n1904, args.bibleol)
        corpora["n1904"] = args.n1904_version

    apply_corrections(con, args.corrections)
    build_plans(con)
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "bhsa_version": args.version,
        "corpora": json.dumps(corpora),
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "BHSA by the ETCBC, https://github.com/ETCBC/bhsa; "
                  "N1904 by CBLC/ETCBC, https://github.com/CenterBLC/N1904",
        "license": "BHSA: CC BY-NC 4.0; N1904: MIT; MACULA Greek: CC BY 4.0; "
                   "Greek glosses: Bible Online Learner (Ezer IT Consulting), with permission",
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.executescript(INDEXES)
    con.commit()
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
