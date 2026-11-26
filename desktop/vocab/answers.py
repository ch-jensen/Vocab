"""Checking typed answers against glosses, and turning the result into an FSRS rating."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from fsrs import Rating

# Default reference time before the user has a history (milliseconds).
DEFAULT_REFERENCE_MS = 6000
MIN_REFERENCE_MS, MAX_REFERENCE_MS = 2000, 20000
SLOW_FACTOR = 2.0   # slower than 2 x reference time -> Hard
FAST_FACTOR = 0.5   # faster than 0.5 x reference time -> Easy

_LEADING = re.compile(r"^(to|the|a|an)\s+")


def split_glosses(gloss: str) -> list[str]:
    """'say; speak, tell' -> ['say', 'speak', 'tell']."""
    return [g.strip() for g in re.split(r"[;,]", gloss) if g.strip()]


def normalize(text: str) -> str:
    """Normalise an answer or gloss for comparison.

    Lowercases, drops text in parentheses ('god(s)' -> 'god'), keeps the text
    of angle-bracket glosses ('<object marker>' -> 'object marker'), removes a
    leading 'to'/'the'/'a'/'an', strips punctuation and extra spaces.
    """
    text = text.lower().strip()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("<", " ").replace(">", " ")
    text = re.sub(r"[^\w\s'-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING.sub("", text)
    return text


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance (Levenshtein + adjacent transpositions)."""
    if a == b:
        return 0
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def allowed_typos(target: str) -> int:
    if len(target) >= 8:
        return 2
    if len(target) >= 4:
        return 1
    return 0


@dataclass(frozen=True)
class AnswerResult:
    correct: bool
    typo: bool = False
    matched: str | None = None   # the gloss that matched


def check_answer(answer: str, glosses: list[str]) -> AnswerResult:
    given = normalize(answer)
    if not given:
        return AnswerResult(False)
    targets = [(g, normalize(g)) for g in glosses]
    for original, target in targets:
        if given == target:
            return AnswerResult(True, False, original)
    for original, target in targets:
        if target and edit_distance(given, target) <= allowed_typos(target):
            return AnswerResult(True, True, original)
    return AnswerResult(False)


def reference_time(durations_ms: list[int]) -> float:
    """The user's typical time for a correct answer (median of recent ones)."""
    if len(durations_ms) < 10:
        return DEFAULT_REFERENCE_MS
    return min(max(statistics.median(durations_ms), MIN_REFERENCE_MS), MAX_REFERENCE_MS)


def rating_for(result: AnswerResult, duration_ms: int, reference_ms: float,
               is_new: bool = False) -> Rating:
    """Map a typed answer to an FSRS rating.

    Wrong -> Again. Correct with a typo or slow -> Hard. Fast -> Easy (but never
    on the first time a word is seen). Otherwise Good.
    """
    if not result.correct:
        return Rating.Again
    if result.typo or duration_ms > SLOW_FACTOR * reference_ms:
        return Rating.Hard
    if not is_new and duration_ms < FAST_FACTOR * reference_ms:
        return Rating.Easy
    return Rating.Good
