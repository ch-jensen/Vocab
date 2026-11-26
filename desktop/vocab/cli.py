"""Command-line front end for trying the engine before the desktop UI exists.

    python -m vocab plans
    python -m vocab new-deck "Frequency" --plan hebrew-frequency --new-per-day 10
    python -m vocab new-deck "Jonah verbs" --pos verb --book Jona --split-stems
    python -m vocab decks
    python -m vocab study "Frequency"            # type the gloss
    python -m vocab study "Frequency" --self     # show answer, rate 1-4
    python -m vocab import-scores ..\\English_score.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from fsrs import Rating

from . import decks as decks_mod
from .decks import DeckConfig, Passage
from .migrate import import_score_csv
from .session import StudySession
from .store import Store

GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def human_interval(due: datetime) -> str:
    seconds = (due - datetime.now(timezone.utc)).total_seconds()
    if seconds < 3600:
        return f"{max(round(seconds / 60), 1)} min"
    if seconds < 86400:
        return f"{round(seconds / 3600)} h"
    days = seconds / 86400
    return f"{round(days)} days" if days < 60 else f"{days / 30:.1f} months"


def show_item(item) -> None:
    text = "".join(
        (f"{BOLD}{YELLOW}[{w.form}]{RESET}" if w.node == item.node else w.form) + w.trailer
        for w in item.clause)
    print()
    print(f"  {text}")
    print(f"  ({item.reference}){'   NEW' if item.is_new else ''}")


def show_facts(store: Store, item) -> None:
    print(f"  {item.voc_lex_utf8}  ({item.sp}, rank {item.rank}, {item.freq}x)", end="")
    if item.stem != "NA":
        stems = ", ".join(f"{s} {n}" for s, n in store.stem_counts(item.key.lex_id))
        print(f"  this form: {item.stem} {item.tense}; stems: {stems}", end="")
    print()


def cmd_study(store: Store, args) -> None:
    deck = decks_mod.get_deck(store, args.deck)
    if deck is None:
        sys.exit(f"No deck called {args.deck!r}. See: python -m vocab decks")
    session = StudySession(store, deck)
    print(f"Deck {deck.name}: {len(session.keys)} cards. Empty answer = don't know, 'q' = quit.")
    while True:
        c = session.counts()
        item = session.next_item()
        if item is None:
            print("\nNothing more to study today in this deck.")
            break
        print(f"\n{GREEN}{c.new} new{RESET}  {RED}{c.learning} learning{RESET}  {c.review} review")
        show_item(item)
        start = time.monotonic()
        if args.self_grade:
            if input("  Enter = show answer, q = quit ").strip().lower() == "q":
                break
            print(f"  {BOLD}{item.gloss}{RESET}")
            show_facts(store, item)
            choice = input("  1 again  2 hard  3 good  4 easy > ").strip()
            if choice == "q":
                break
            if choice not in {"1", "2", "3", "4"}:
                choice = "3"
            outcome = session.rate(item, Rating(int(choice)), int((time.monotonic() - start) * 1000))
        else:
            text = input("  Gloss > ")
            duration = int((time.monotonic() - start) * 1000)
            if text.strip().lower() == "q":
                break
            outcome = session.answer(item, text, duration)
            r = outcome.result
            if r.correct:
                note = f" (typo, read: {r.matched})" if r.typo else ""
                print(f"  {GREEN}Correct{RESET}{note}: {item.gloss}")
            else:
                print(f"  {RED}Wrong{RESET}: {item.gloss}")
            show_facts(store, item)
        print(f"  {outcome.rating.name} -> next in {human_interval(outcome.due)}")


def cmd_new_deck(store: Store, args) -> None:
    cfg = DeckConfig(
        plan_id=args.plan,
        languages=args.lang or (["Aramaic"] if args.plan == "aramaic-frequency" else ["Hebrew"]),
        pos=args.pos, rank_min=args.rank[0] if args.rank else None,
        rank_max=args.rank[1] if args.rank else None,
        stems=args.stems, tenses=args.tenses, suffix=args.suffix,
        passages=[Passage(b) for b in args.book] if args.book else None,
        split_stems=args.split_stems, gloss_language=args.gloss,
        new_per_day=args.new_per_day, max_reviews_per_day=args.max_reviews,
        desired_retention=args.retention,
    )
    deck = decks_mod.create_deck(store, args.name, cfg)
    n = len(decks_mod.deck_cards(store.con, cfg))
    print(f"Created deck {deck.name!r} with {n} cards.")


def cmd_decks(store: Store, args) -> None:
    for deck in decks_mod.list_decks(store):
        c = StudySession(store, deck).counts()
        print(f"{deck.name:30} new {c.new:4}  learning {c.learning:4}  review {c.review:4}")


def cmd_plans(store: Store, args) -> None:
    for p in decks_mod.plans(store):
        print(f"{p['plan_id']:28} {p['size']:5} lexemes  {p['name']}")


def cmd_import(store: Store, args) -> None:
    for path in args.files:
        r = import_score_csv(store, path)
        print(f"{path}: {r.imported} imported, {r.skipped_existing} already present, {r.unknown} unknown")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m vocab")
    ap.add_argument("--user-db", help="user database (default: %%APPDATA%%\\Vocab\\user.sqlite)")
    ap.add_argument("--bhsa-db", help="BHSA database (default: desktop\\data\\bhsa_vocab.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("plans", help="list predefined study plans")
    sub.add_parser("decks", help="list decks with today's counts")

    s = sub.add_parser("study", help="study a deck")
    s.add_argument("deck")
    s.add_argument("--self", dest="self_grade", action="store_true",
                   help="show the answer and rate yourself instead of typing")

    n = sub.add_parser("new-deck", help="create a deck")
    n.add_argument("name")
    n.add_argument("--plan", help="predefined plan id (see 'plans')")
    n.add_argument("--lang", nargs="+", choices=["Hebrew", "Aramaic"])
    n.add_argument("--pos", nargs="+", help="parts of speech, e.g. verb subs adjv")
    n.add_argument("--rank", nargs=2, type=int, metavar=("MIN", "MAX"))
    n.add_argument("--stems", nargs="+")
    n.add_argument("--tenses", nargs="+")
    n.add_argument("--suffix", choices=["any", "with", "without"], default="any")
    n.add_argument("--book", nargs="+", help="BHSA book names, e.g. Genesis Jona")
    n.add_argument("--split-stems", action="store_true", help="one card per verbal stem")
    n.add_argument("--gloss", default="English")
    n.add_argument("--new-per-day", type=int, default=10)
    n.add_argument("--max-reviews", type=int, default=200)
    n.add_argument("--retention", type=float, default=0.9)

    i = sub.add_parser("import-scores", help="import *_score.csv files from the notebook version")
    i.add_argument("files", nargs="+")

    args = ap.parse_args(argv)
    with Store(args.user_db, args.bhsa_db) as store:
        {"study": cmd_study, "new-deck": cmd_new_deck, "decks": cmd_decks,
         "plans": cmd_plans, "import-scores": cmd_import}[args.cmd](store, args)


if __name__ == "__main__":
    main()
