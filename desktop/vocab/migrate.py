"""Import score files from the notebook version (English_score.csv, Danish_score.csv, ...).

The old file has one row per lexeme: lex, node, time_score (seconds for the last
answer), time_stamp (Unix time of the last answer, pushed back for wrong
answers) and rep (a mistake counter, at least 1).

The notebook counted a lexeme as due when
    level = elapsed_days * time_score * rep / mean_time_score
exceeded a threshold (2 by default). Solving for elapsed_days gives the
interval the old program used, which becomes the FSRS stability (at 90%
retention, the FSRS interval is about equal to the stability). More mistakes
give a higher FSRS difficulty.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fsrs import State

from .decks import ALL_STEMS
from .store import Store, ts

OLD_THRESHOLD = 2.0
MIN_STABILITY, MAX_STABILITY = 0.5, 365.0


@dataclass
class ImportReport:
    imported: int = 0
    skipped_existing: int = 0
    unknown: int = 0


def old_interval_days(time_score: float, rep: float, mean_score: float,
                      threshold: float = OLD_THRESHOLD) -> float:
    if time_score <= 0 or rep <= 0:
        return MIN_STABILITY
    return threshold * mean_score / (time_score * rep)


def import_score_csv(store: Store, path: Path | str, threshold: float = OLD_THRESHOLD) -> ImportReport:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("lex")]
    report = ImportReport()
    if not rows:
        return report

    scores = [float(r["time_score"]) for r in rows if r.get("time_score")]
    mean_score = statistics.mean(scores) if scores else 1.0
    now = datetime.now(timezone.utc)

    for r in rows:
        lex_id = _lex_id(store, r["lex"], r.get("node"))
        if lex_id is None:
            report.unknown += 1
            continue
        if store.con.execute("SELECT 1 FROM cards WHERE lex_id = ? AND stem = ?",
                             (lex_id, ALL_STEMS)).fetchone():
            report.skipped_existing += 1
            continue
        time_score = float(r.get("time_score") or 0)
        rep = float(r.get("rep") or 1)
        last = datetime.fromtimestamp(float(r["time_stamp"]), timezone.utc)
        last = min(last, now)
        stability = min(max(old_interval_days(time_score, rep, mean_score, threshold),
                            MIN_STABILITY), MAX_STABILITY)
        difficulty = min(max(4.0 + 1.5 * (rep - 1), 1.0), 10.0)
        due = last + timedelta(days=stability)
        store.con.execute(
            "INSERT INTO cards (lex_id, stem, state, step, stability, difficulty, due, last_review, created_at) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)",
            (lex_id, ALL_STEMS, int(State.Review), stability, difficulty, ts(due), ts(last), ts(now)))
        report.imported += 1
    store.con.commit()
    return report


def _lex_id(store: Store, lex: str, node: str | None) -> str | None:
    """Find the lexeme: by the stored word node if possible, else by lex (Hebrew first)."""
    if node:
        try:
            row = store.con.execute("SELECT lex_id FROM bhsa.words WHERE node = ?",
                                    (int(float(node)),)).fetchone()
        except ValueError:
            row = None
        if row and row[0].split(":", 1)[1] == lex:
            return row[0]
    row = store.con.execute(
        "SELECT lex_id FROM bhsa.lexemes WHERE lex = ? ORDER BY language = 'Hebrew' DESC",
        (lex,)).fetchone()
    return row[0] if row else None
