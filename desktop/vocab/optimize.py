"""Fitting the FSRS parameters to the user's own review history.

Uses fsrs-rs (the Rust implementation of FSRS that Anki uses) through the
fsrs-rs-python package. The fitted parameters are only kept if they predict
the user's answers better than the current ones, as Anki does.

Each word's history becomes training items in the fsrs-rs format: a list of
(rating, days since the previous review). Words whose history did not start
here (imported from the notebook version) are left out, because their first
review in this app was not a first meeting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

import fsrs_rs_python as rs
from fsrs import Scheduler
from fsrs.scheduler import DEFAULT_PARAMETERS

from .session import fsrs_parameters
from .stats import study_day
from .store import Store, parse_ts, ts

MIN_REVIEWS = 400          # below this, the defaults are better than a fit
RELEARNING_STEPS = 1       # matches the scheduler's relearning steps (10 min)


@dataclass
class TrainingData:
    items: list            # list[rs.FSRSItem]
    reviews: int           # reviews used


@dataclass
class OptimizeResult:
    parameters: list[float]
    reviews: int
    items: int
    loss_before: float
    loss_after: float
    applied: bool
    message: str


def training_data(store: Store, tz: tzinfo | None = None) -> TrainingData:
    rows = store.con.execute("""
        SELECT r.card_id, r.reviewed_at, r.rating, r.state_before FROM reviews r
        ORDER BY r.card_id, r.reviewed_at, r.review_id""").fetchall()
    histories: dict[int, list[tuple]] = {}
    for card_id, at, rating, state_before in rows:
        histories.setdefault(card_id, []).append((study_day(parse_ts(at), tz), rating, state_before))

    items, used = [], 0
    for history in histories.values():
        if history[0][2] != 0:        # first review here was not of a new word
            continue
        reviews, deltas, prev_day = [], [], None
        for day, rating, _ in history:
            delta = 0 if prev_day is None else (day - prev_day).days
            reviews.append(rs.FSRSReview(rating, delta))
            deltas.append(delta)
            prev_day = day
        used += len(reviews)
        for i in range(1, len(reviews)):
            if deltas[i] > 0:                   # items end with a review on a later day
                items.append(rs.FSRSItem(reviews[: i + 1]))
    return TrainingData(items, used)


def total_reviews(store: Store) -> int:
    return store.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]


def fit(data: TrainingData, current: list[float] | None) -> OptimizeResult:
    """Fit parameters (pure computation; safe to run in a background thread)."""
    current = list(current or DEFAULT_PARAMETERS)
    if data.reviews < MIN_REVIEWS or len(data.items) < 50:
        return OptimizeResult(current, data.reviews, len(data.items), 0, 0, False,
                              f"At least {MIN_REVIEWS} reviews are needed; you have {data.reviews}.")
    new = list(rs.FSRS(current).compute_parameters(
        data.items, enable_short_term=True, num_relearning_steps=RELEARNING_STEPS))
    before = rs.FSRS(current).evaluate(data.items).log_loss
    after = rs.FSRS(new).evaluate(data.items).log_loss
    try:
        Scheduler(parameters=new)             # check py-fsrs accepts them
    except ValueError as exc:
        return OptimizeResult(current, data.reviews, len(data.items), before, after, False,
                              f"The fitted parameters could not be used ({exc}).")
    if after >= before:
        return OptimizeResult(current, data.reviews, len(data.items), before, after, False,
                              "Your current parameters already fit your answers best; kept them.")
    return OptimizeResult(new, data.reviews, len(data.items), before, after, True,
                          "Scheduling is now fitted to your own answers.")


def apply(store: Store, result: OptimizeResult, now: datetime | None = None) -> None:
    if not result.applied:
        return
    now = now or datetime.now(timezone.utc)
    store.set_meta("fsrs_parameters", json.dumps(result.parameters))
    store.set_meta("fsrs_optimized_at", ts(now))
    store.set_meta("fsrs_optimized_reviews", str(result.reviews))


def reset(store: Store) -> None:
    """Go back to the default parameters."""
    store.con.execute("DELETE FROM meta WHERE key IN "
                      "('fsrs_parameters', 'fsrs_optimized_at', 'fsrs_optimized_reviews')")
    store.con.commit()


def status(store: Store) -> str:
    if fsrs_parameters(store) is None:
        return "Default FSRS parameters (not yet fitted to your answers)."
    at = parse_ts(store.get_meta("fsrs_optimized_at"))
    n = store.get_meta("fsrs_optimized_reviews")
    when = at.astimezone().strftime("%d %b %Y") if at else "?"
    return f"Fitted to your answers on {when} ({n} reviews)."
