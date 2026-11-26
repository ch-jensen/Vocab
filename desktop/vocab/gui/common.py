"""Shared helpers for the desktop UI: fonts, labels, formatting."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtGui import QFont

# Fonts with full support for Hebrew vowels and cantillation, best first.
# A font is only used if it is installed; Times New Roman is the last resort.
HEBREW_FONTS = ["SBL Hebrew", "Ezra SIL", "Taamey Frank CLM", "Noto Serif Hebrew",
                "Times New Roman"]

POS_LABELS = {
    "subs": "noun", "verb": "verb", "adjv": "adjective", "advb": "adverb",
    "prep": "preposition", "conj": "conjunction", "nmpr": "proper noun",
    "art": "article", "prps": "personal pronoun", "prde": "demonstrative pronoun",
    "prin": "interrogative pronoun", "inrg": "interrogative particle",
    "nega": "negative", "intj": "interjection",
}

TENSE_LABELS = {
    "perf": "qatal (perfect)", "impf": "yiqtol (imperfect)", "wayq": "wayyiqtol",
    "impv": "imperative", "infc": "infinitive construct", "infa": "infinitive absolute",
    "ptca": "active participle", "ptcp": "passive participle",
}

STEM_LABELS = {
    "qal": "qal", "nif": "nifal", "piel": "piel", "pual": "pual", "hit": "hitpael",
    "hif": "hifil", "hof": "hofal", "hsht": "hishtafal", "pasq": "passive qal",
    "poel": "poel", "poal": "poal", "htpo": "hitpoel", "hotp": "hotpaal", "nit": "nitpael",
    "tif": "tifil", "peal": "peal", "peil": "peil", "pael": "pael", "haf": "hafel",
    "afel": "afel", "shaf": "shafel", "htpe": "hitpeel", "htpa": "hitpaal",
    "etpa": "etpaal", "etpe": "etpeel",
}

ACCENT = "#b7791f"      # highlight colour for the word being asked
GOOD = "#2f855a"
BAD = "#c53030"
MUTED = "#718096"


def hebrew_font(point_size: int) -> QFont:
    font = QFont()
    font.setFamilies(HEBREW_FONTS)
    font.setPointSize(point_size)
    return font


def interval_text(due: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    seconds = max((due - now).total_seconds(), 0)
    if seconds < 3600:
        return f"{max(round(seconds / 60), 1)} min"
    if seconds < 86400:
        return f"{round(seconds / 3600)} h"
    days = seconds / 86400
    if days < 31:
        return f"{round(days)} d"
    if days < 365:
        return f"{days / 30.4:.1f} mo"
    return f"{days / 365:.1f} y"


def stem_label(stem: str) -> str:
    return STEM_LABELS.get(stem, stem)
