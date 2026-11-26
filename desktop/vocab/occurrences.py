"""Choosing which attested occurrence of a word to show.

The card is the word; the occurrence shown changes from review to review, so
the learner meets the forms that actually occur in the text:

1. Occurrences are grouped by form (pointed form without accents).
2. Forms the learner has not been shown yet come first.
3. Among those, a form is drawn at random, weighted by the square root of its
   count: frequent forms come up more often, but rare forms still appear.
4. Within the form, an occurrence not shown before is preferred; otherwise the
   one shown longest ago.
"""

from __future__ import annotations

import math
import random
import re
import sqlite3
from collections import defaultdict

# Cantillation marks (U+0591-U+05AF), meteg, rafe, paseq, sof pasuq and the
# upper/lower dots. Vowels, dagesh, shin/sin dots and qamats qatan are kept.
_ACCENTS = re.compile("[֑-ֽֿ֯׀׃-׆]")


def strip_accents(form: str) -> str:
    return _ACCENTS.sub("", form)


def choose_occurrence(candidates: list[sqlite3.Row] | list[tuple[int, str]],
                      last_shown: dict[int, str],
                      rng: random.Random) -> int:
    """Pick a word node.

    candidates: (node, form_utf8) pairs for the card.
    last_shown: node -> time last shown (ISO string), for nodes shown before.
    """
    if not candidates:
        raise ValueError("no occurrences to choose from")

    by_form: dict[str, list[int]] = defaultdict(list)
    for node, form in candidates:
        by_form[strip_accents(form)].append(node)

    seen_forms = {f for f, nodes in by_form.items() if any(n in last_shown for n in nodes)}
    pool = [f for f in by_form if f not in seen_forms] or list(by_form)
    pool.sort()  # deterministic order for a seeded rng
    weights = [math.sqrt(len(by_form[f])) for f in pool]
    form = rng.choices(pool, weights=weights, k=1)[0]

    nodes = by_form[form]
    unseen = [n for n in nodes if n not in last_shown]
    if unseen:
        return rng.choice(unseen)
    return min(nodes, key=lambda n: last_shown[n])
