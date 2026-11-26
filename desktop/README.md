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
