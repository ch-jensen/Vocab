# Vocab desktop: data build (Phase 1)

`build_db.py` turns the BHSA (via Text-Fabric) into one read-only SQLite file,
`data/bhsa_vocab.sqlite`, which the desktop app will ship with. End users never need
Text-Fabric, Jupyter or an internet connection.

## Build

Requires `text-fabric` and the BHSA 2021 data in `~/text-fabric-data`
(download once with `from tf.app import use; use('ETCBC/bhsa')`).

```
python build_db.py
python -m pytest tests
```

The build takes about 15 seconds and produces a file of about 64 MB. Every `*_glosses.csv`
in the repository root (for example `Danish_glosses.csv`) is imported automatically.
The database is generated, so it isn't committed.

## Contents

| Table | Contents |
|---|---|
| `lexemes` | 9,230 lexemes. `lex_id` = `hbo:<lex>` or `arc:<lex>` (stable across BHSA versions), with frequency, `rank_lex` (0 = most frequent), part of speech and Hebrew forms |
| `lexeme_stems` | occurrences per lexeme and verbal stem |
| `words` | all 426,590 occurrences: pointed form, trailer, qere, stem, tense, person/number/gender, state and pronominal suffix, with the clause and verse each belongs to |
| `clauses`, `verses` | context. A clause's text is `form_utf8 + trailer_utf8` of its words, ordered by `node` |
| `glosses` | per gloss language, lexeme and stem (`default` or a stem such as `piel`) |
| `plans`, `plan_items` | predefined study orders: Hebrew by frequency (with or without proper nouns) and Aramaic by frequency |
| `meta` | schema version, BHSA version, build time, licence |

Data: BHSA by the ETCBC, licensed CC BY-NC 4.0, so the app must stay non-commercial and credit the ETCBC.

# Phase 2: the engine (`vocab/`)

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

| Module | Purpose |
|---|---|
| `store.py` | The user database (`%APPDATA%\Vocab\user.sqlite`) with the BHSA database attached read-only as `bhsa` |
| `decks.py` | Deck definitions (`DeckConfig`): a predefined plan or filters, and the SQL that turns them into cards and occurrences |
| `occurrences.py` | Chooses which attested form to show: forms not seen yet first, weighted by frequency |
| `answers.py` | Answer checking (several glosses, parentheses, a leading "to", typos) and mapping to FSRS ratings using correctness and response time |
| `session.py` | The daily queue (learning → due reviews → new cards, with daily limits; the day starts at 04:00) and FSRS scheduling |
| `migrate.py` | Imports `*_score.csv` files from the notebook version |
| `cli.py` | A command-line study loop for trying it out: `python -m vocab --help` |

**Cards.** A card is a lexeme (stem `*`) or, with `split_stems`, a lexeme plus a verbal stem. The
review state is shared by all decks, so a word learned in one deck counts in every other deck.
Each review shows a different attested occurrence in its clause.

**Ratings.** Wrong → Again; correct with a typo, or slower than 2 × your median time → Hard;
faster than 0.5 × your median time → Easy (never on a word's first showing); otherwise Good.
Self-grading (`study --self`) works like Anki's "show answer" mode.

**Not yet done.** Fitting FSRS parameters to a user's own history (the `fsrs_parameters` meta
key is read but nothing writes it yet), statistics, and the desktop UI.
