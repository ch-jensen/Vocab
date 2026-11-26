"""Exporting and importing decks (.vocabdeck files)."""

import json

import pytest
from fsrs import Rating

from vocab import deckfile, decks, glosses
from vocab.decks import DeckConfig, Passage
from vocab.session import StudySession
from vocab.store import DEFAULT_BHSA_DB, Store

pytestmark = pytest.mark.skipif(not DEFAULT_BHSA_DB.exists(), reason="run build_db.py first")


@pytest.fixture
def two_users(tmp_path):
    with Store(tmp_path / "teacher.sqlite") as a, Store(tmp_path / "student.sqlite") as b:
        yield a, b


def test_round_trip_between_users(two_users, tmp_path):
    teacher, student = two_users
    cfg = DeckConfig(pos=["verb"], passages=[Passage("Genesis", 1, 11), Passage("Jona")],
                     gloss_language="Danish", new_per_day=7, answer_mode="self", split_stems=True)
    deck = decks.create_deck(teacher, "Genesis 1-11 and Jonah: verbs", cfg)
    glosses.set_gloss(teacher, "hbo:BR>[", "Danish", "qal", "skabe (kun om Gud)")
    glosses.set_gloss(teacher, "hbo:W", "Danish", "default", "og")       # not in this deck
    # Teacher's progress must not travel with the deck.
    s = StudySession(teacher, deck)
    s.rate(s.next_item(), Rating.Easy)

    path = tmp_path / "deck.vocabdeck"
    assert deckfile.export_deck(teacher, deck, path) == 1                  # only the deck's words
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "vocab-deck" and data["bhsa_version"] == "2021"
    assert "cards" not in data and "reviews" not in data

    result = deckfile.import_deck(student, path)
    assert result.deck.name == "Genesis 1-11 and Jonah: verbs" and not result.renamed
    assert result.deck.config == cfg
    assert result.words == len(decks.deck_cards(teacher.con, cfg))
    assert result.glosses_added == 1 and result.warnings == []
    assert student.glosses("hbo:BR>[", "Danish")["qal"] == "skabe (kun om Gud)"
    assert student.con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0


def test_own_glosses_are_kept_and_names_made_unique(two_users, tmp_path):
    teacher, student = two_users
    deck = decks.create_deck(teacher, "Verbs", DeckConfig(pos=["verb"], rank_max=30))
    glosses.set_gloss(teacher, "hbo:>MR[", "English", "default", "say, speak, think")
    path = tmp_path / "verbs.vocabdeck"
    deckfile.export_deck(teacher, deck, path)

    glosses.set_gloss(student, "hbo:>MR[", "English", "default", "say (my own)")
    decks.create_deck(student, "Verbs", DeckConfig())
    result = deckfile.import_deck(student, path)
    assert result.deck.name == "Verbs (2)" and result.renamed
    assert (result.glosses_added, result.glosses_kept) == (0, 1)
    assert student.glosses("hbo:>MR[", "English")["default"] == "say (my own)"
    assert deckfile.import_deck(student, path).deck.name == "Verbs (3)"


def test_new_gloss_language_travels_with_the_deck(two_users, tmp_path):
    teacher, student = two_users
    glosses.set_gloss(teacher, "hbo:>MR[", "German", "default", "sagen")
    glosses.set_gloss(teacher, "hbo:HJH[", "German", "default", "sein")
    deck = decks.create_deck(teacher, "Deutsch", DeckConfig(gloss_language="German"))
    path = tmp_path / "de.vocabdeck"
    assert deckfile.export_deck(teacher, deck, path) == 2
    result = deckfile.import_deck(student, path)
    assert result.words == 2 and "German" in student.gloss_languages()


@pytest.mark.parametrize("content, message", [
    ("not json", "could not be read"),
    ('{"format": "something-else"}', "not a Vocab deck"),
    ('{"format": "vocab-deck", "format_version": 99, "name": "x", "config": {}}', "newer version"),
    ('{"format": "vocab-deck", "format_version": 1, "name": "x", "config": {"suffix": "maybe"}}',
     "not valid"),
    ('{"format": "vocab-deck", "format_version": 1, "name": "x", '
     '"config": {"passages": [{"book": "Hezekiah"}]}}', "unknown books"),
    ('{"format": "vocab-deck", "format_version": 1, "name": "x", "config": {"plan_id": "nope"}}',
     "study plan"),
])
def test_bad_files(two_users, tmp_path, content, message):
    _, student = two_users
    path = tmp_path / "bad.vocabdeck"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        deckfile.import_deck(student, path)
    assert decks.list_decks(student) == []
