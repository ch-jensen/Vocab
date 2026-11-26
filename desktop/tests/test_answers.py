from fsrs import Rating

from vocab.answers import (AnswerResult, check_answer, edit_distance, normalize,
                           rating_for, reference_time, split_glosses)


def test_split_glosses():
    assert split_glosses("say; speak, tell") == ["say", "speak", "tell"]
    assert split_glosses("") == []


def test_normalize():
    assert normalize("god(s)") == "god"
    assert normalize("  To Say! ") == "say"
    assert normalize("<object marker>") == "object marker"
    assert normalize("the") == "the"          # a gloss that is only an article stays
    assert normalize("the man") == "man"


def test_edit_distance():
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("house", "huose") == 1   # transposition
    assert edit_distance("", "abc") == 3


def test_check_answer_exact_and_variants():
    glosses = split_glosses("say; speak")
    assert check_answer("speak", glosses) == AnswerResult(True, False, "speak")
    assert check_answer("to say", glosses).correct
    assert not check_answer("", glosses).correct
    assert not check_answer("go", glosses).correct


def test_check_answer_typos():
    r = check_answer("hosue", ["house"])
    assert r.correct and r.typo
    assert not check_answer("hat", ["cat"]).correct     # too short for a typo
    assert check_answer("brothre", ["brother"]).typo


def test_rating_for():
    ok = AnswerResult(True)
    ref = 6000
    assert rating_for(AnswerResult(False), 1000, ref) == Rating.Again
    assert rating_for(AnswerResult(True, True), 1000, ref) == Rating.Hard
    assert rating_for(ok, 20000, ref) == Rating.Hard
    assert rating_for(ok, 5000, ref) == Rating.Good
    assert rating_for(ok, 2000, ref) == Rating.Easy
    assert rating_for(ok, 2000, ref, is_new=True) == Rating.Good


def test_reference_time():
    assert reference_time([1000] * 5) == 6000        # too little history: default
    assert reference_time([3000] * 20) == 3000
    assert reference_time([100] * 20) == 2000        # clamped
