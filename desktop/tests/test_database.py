"""Consistency checks for the built database (run after build_db.py).

    python -m pytest desktop/tests
"""

import sqlite3
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parents[1] / "data" / "bhsa_vocab.sqlite"


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        pytest.skip(f"{DB} not built; run build_db.py first")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield con
    con.close()


def one(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def test_meta(con):
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["schema_version"] == "2"
    assert meta["bhsa_version"] == "2021"
    assert "CC BY-NC" in meta["license"]
    assert '"n1904": "1.0.0"' in meta["corpora"]


def test_sizes(con):
    # BHSA 2021: 426,590 words, 23,213 verses, 39 books.
    bhsa = "lex_id IN (SELECT lex_id FROM lexemes WHERE corpus = 'bhsa')"
    assert one(con, f"SELECT COUNT(*) FROM words WHERE {bhsa}") == 426590
    assert one(con, "SELECT COUNT(*) FROM verses WHERE corpus = 'bhsa'") == 23213
    assert one(con, "SELECT COUNT(DISTINCT book) FROM verses WHERE corpus = 'bhsa'") == 39
    assert one(con, "SELECT COUNT(*) FROM lexemes WHERE corpus = 'bhsa'") > 9000


def test_greek_new_testament(con):
    # N1904: 137,779 words, 7,944 verses, 27 books, 5,396 lemmas.
    greek = "lex_id IN (SELECT lex_id FROM lexemes WHERE corpus = 'n1904')"
    assert one(con, f"SELECT COUNT(*) FROM words WHERE {greek}") == 137779
    assert one(con, "SELECT COUNT(*) FROM verses WHERE corpus = 'n1904'") == 7944
    assert one(con, "SELECT COUNT(DISTINCT book) FROM verses WHERE corpus = 'n1904'") == 27
    assert one(con, "SELECT COUNT(*) FROM lexemes WHERE language = 'Greek'") == 5396
    # Greek and Hebrew node ranges do not overlap, and Greek words come after Hebrew ones.
    assert one(con, f"SELECT MIN(node) FROM words WHERE {greek}") > \
        one(con, "SELECT MAX(node) FROM words WHERE lex_id LIKE 'hbo:%' OR lex_id LIKE 'arc:%'")
    # Every Greek word has a context range around itself; Hebrew words use clauses.
    assert one(con, f"SELECT COUNT(*) FROM words WHERE {greek} AND NOT "
                    "(ctx_from <= node AND node <= ctx_to)") == 0
    assert one(con, "SELECT COUNT(*) FROM words WHERE ctx_from IS NOT NULL AND lex_id LIKE 'hbo:%'") == 0
    # Text is in NFC, like the gloss files.
    import unicodedata
    forms = [f for (f,) in con.execute(f"SELECT form_utf8 FROM words WHERE {greek} LIMIT 5000")]
    assert all(f == unicodedata.normalize("NFC", f) for f in forms)
    # Glosses from Bible Online Learner for every lemma in English and Danish.
    for language in ("English", "Danish"):
        assert one(con, "SELECT COUNT(*) FROM glosses WHERE gloss_language = ? AND lex_id LIKE 'grc:%'",
                   language) == 5396
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id = 'grc:λόγος' AND gloss_language = 'Danish'") == "ord"
    assert one(con, "SELECT sp FROM lexemes WHERE lex_id = 'grc:Ἰησοῦς'") == "nmpr"
    assert one(con, "SELECT lex_id FROM plan_items WHERE plan_id = 'greek-frequency' AND position = 1") == "grc:ὁ"


def test_word_counts_match_lexeme_frequency(con):
    bad = con.execute("""
        SELECT l.lex_id, l.freq, COUNT(w.node)
        FROM lexemes l LEFT JOIN words w USING (lex_id)
        GROUP BY l.lex_id HAVING l.freq <> COUNT(w.node)
    """).fetchall()
    assert bad == []


def test_stem_counts_add_up(con):
    bad = con.execute("""
        SELECT l.lex_id FROM lexemes l JOIN lexeme_stems s USING (lex_id)
        GROUP BY l.lex_id HAVING SUM(s.freq) <> l.freq
    """).fetchall()
    assert bad == []


def test_foreign_keys(con):
    assert one(con, "SELECT COUNT(*) FROM words WHERE lex_id NOT IN (SELECT lex_id FROM lexemes)") == 0
    assert one(con, "SELECT COUNT(*) FROM words WHERE clause_id NOT IN (SELECT clause_id FROM clauses)") == 0
    assert one(con, "SELECT COUNT(*) FROM words WHERE verse_id NOT IN (SELECT verse_id FROM verses)") == 0
    assert one(con, "SELECT COUNT(*) FROM clauses WHERE verse_id NOT IN (SELECT verse_id FROM verses)") == 0


def test_genesis_1_1_text(con):
    verse_id = one(con, "SELECT verse_id FROM verses WHERE book='Genesis' AND chapter=1 AND verse=1")
    text = "".join(f + t for f, t in con.execute(
        "SELECT form_utf8, trailer_utf8 FROM words WHERE verse_id=? ORDER BY node", (verse_id,)))
    # Compare consonants only: the order of vowel/accent marks is not fixed.
    consonants = "".join(ch for ch in text if "א" <= ch <= "ת" or ch in " ׃")
    assert consonants.strip() == "בראשית ברא אלהים את השמים ואת הארץ׃"


def test_clause_text_contains_target_word(con):
    # Reconstruct the clause of the first occurrence of 'to say' and check the word is in it.
    node, clause_id, form = con.execute(
        "SELECT node, clause_id, form_utf8 FROM words WHERE lex_id='hbo:>MR[' ORDER BY node LIMIT 1"
    ).fetchone()
    nodes = [n for (n,) in con.execute("SELECT node FROM words WHERE clause_id=? ORDER BY node", (clause_id,))]
    assert node in nodes


def test_frequent_lexemes(con):
    # 'and' is the most frequent Hebrew lexeme; 'to say' and 'God' are very frequent.
    first = one(con, "SELECT lex_id FROM plan_items WHERE plan_id='hebrew-frequency' AND position=1")
    assert first == "hbo:W"
    assert one(con, "SELECT freq FROM lexemes WHERE lex_id='hbo:>MR['") > 5000
    assert one(con, "SELECT sp FROM lexemes WHERE lex_id='hbo:>MR['") == "verb"
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id='hbo:>MR[' AND gloss_language='English'") == "say"


def test_verb_features(con):
    stems = {s for (s,) in con.execute("SELECT DISTINCT stem FROM words WHERE sp='verb'")}
    assert {"qal", "nif", "piel", "hif", "hit"} <= stems
    assert one(con, "SELECT COUNT(*) FROM words WHERE sp<>'verb' AND stem<>'NA'") == 0
    tenses = {t for (t,) in con.execute("SELECT DISTINCT tense FROM words WHERE sp='verb'")}
    assert {"perf", "impf", "wayq", "ptca", "infc"} <= tenses


def test_suffixes(con):
    n = one(con, "SELECT COUNT(*) FROM words WHERE has_suffix=1")
    assert 40000 < n < 100000
    assert one(con, "SELECT COUNT(*) FROM words WHERE has_suffix=1 AND sfx_person='NA'") == 0


def test_plans_cover_all_lexemes(con):
    for plan_id, language in [("hebrew-frequency", "Hebrew"), ("aramaic-frequency", "Aramaic")]:
        assert one(con, "SELECT COUNT(*) FROM plan_items WHERE plan_id=?", plan_id) == \
            one(con, "SELECT COUNT(*) FROM lexemes WHERE language=?", language)
    assert one(con, """SELECT COUNT(*) FROM plan_items p JOIN lexemes l USING (lex_id)
                       WHERE p.plan_id='hebrew-frequency-no-names' AND l.sp='nmpr'""") == 0
    # Positions follow descending frequency.
    freqs = [f for (f,) in con.execute("""SELECT l.freq FROM plan_items p JOIN lexemes l USING (lex_id)
                                         WHERE p.plan_id='hebrew-frequency' ORDER BY p.position""")]
    assert freqs == sorted(freqs, reverse=True)


def test_every_lexeme_has_english_gloss_or_is_known_gap(con):
    missing = one(con, """SELECT COUNT(*) FROM lexemes WHERE lex_id NOT IN
                          (SELECT lex_id FROM glosses WHERE gloss_language='English')""")
    assert missing < 50


def test_danish_glosses_imported(con):
    langs = {g for (g,) in con.execute("SELECT DISTINCT gloss_language FROM glosses")}
    if "Danish" not in langs:
        pytest.skip("Danish_glosses.csv not imported")
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id='hbo:>B/' AND gloss_language='Danish'") == "far"


def test_gloss_corrections_applied(con):
    """Our corrections (sources/gloss_corrections.csv) replace the source's glosses."""
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id = 'grc:ἀγαπάω' AND gloss_language = 'Danish'") \
        == "elsker"
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id = 'grc:ὁ' AND gloss_language = 'Danish'") \
        == "den, det, de"
    # Other languages are untouched.
    assert one(con, "SELECT gloss FROM glosses WHERE lex_id = 'grc:ἀγαπάω' AND gloss_language = 'English'") \
        == "love"
