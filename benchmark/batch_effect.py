"""Does a message's score depend on which other 24 messages share its request? Spam and harassment.

`benchmark/ai_detect/REPORT2.md` measured this for `ai_generated` and found it large enough to move
items across the shipping threshold. It then said, without measuring it, that the effect belongs to
the batching contract rather than to that one category, so it must apply to spam and harassment too.
Those are the two categories whose action can be `delete`. This file turns that expectation into a
number, in whichever direction the number goes. JEV-56.

Five conditions over the same messages, 25 per request, the production batching contract:

    pure        every message in the batch comes from the same side
    pure2       the identical batches, asked a second time
    reordered   the identical batches, the same 25 messages, shuffled within the batch
    reshuffled  the same side, regrouped: different neighbours, same composition
    mixed       the batch is about half the other side

Each one holds everything constant but one thing, so a flip can be attributed:

- `pure2` changes nothing at all. It is the noise floor.
- `reordered` changes only the position each message occupies. `Judge` keys its state and its
  questions by position (`messages.m3.text`), a shape adopted because lists leaked probabilities
  between neighbours, so position sensitivity is the first rival explanation and needs its own
  control. It also guards against the noise floor being flattered by a byte-identical request: if
  `pure2` is low only because the prompt repeats exactly, `reordered` is the honest noise floor.
- `reshuffled` changes which messages share the batch, holding the composition at all-one-side.
- `mixed` changes the composition as well.

Read the columns left to right. A claim about composition only survives if its column is larger than
every column to its left.

`pure2` is not optional. REPORT2 found 17 of 156 items crossing the threshold with nothing changed
at all, so any effect only exists if it is bigger than the noise floor measured beside it.

Both sides are measured. A clean message drifting up into `delete` and a spam message drifting down
out of it are different failures, and neither shows up in the other's number.

    python -m benchmark.batch_effect pools              # free: what the pools are, what was dropped
    python -m benchmark.batch_effect pilot              # paid, one batch per condition, prints cost
    python -m benchmark.batch_effect ask pure           # paid, and the same for pure2,
    python -m benchmark.batch_effect ask reordered      # reordered, reshuffled and mixed
    python -m benchmark.batch_effect analyse            # free

Every paid command is resumable: results are appended per message and an id already present for that
condition is not asked again.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jevmod.judge import CATEGORIES, Judge, Message, prefilter  # noqa: E402

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "results" / "batch_effect.jsonl"

# The same question set `run_jevmod.py` asks. Asking only spam and harassment would be a different
# prompt from the one the product sends, and the number would not transfer to production.
CATS = [c for c in CATEGORIES if c != "offtopic"]
BATCH = 25

# From DEFAULT_THRESHOLDS in jevmod/core/policy.py. These are the lines a drift has to cross for the
# drift to mean anything to a server owner.
THRESHOLD = {"spam": 0.85, "harassment": 0.75}

# Seeded so the run repeats. The pools and the batch order are a property of this number.
SEED = 56
RESHUFFLE_SEED = 560  # a different grouping of the same pools, not a different pool
REORDER_SEED = 5600   # a different order inside each batch, not a different batch
PER_POOL = 150
CONDITIONS = ("pure", "pure2", "reordered", "reshuffled", "mixed")


def _items() -> list[dict]:
    return [json.loads(line) for line in (DATA / "items.jsonl").open(encoding="utf-8")]


def pools() -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Four pools of 150, and what had to be thrown away to build them.

    Pre-filtered items are dropped here rather than discovered as holes in the results: under eight
    alphanumerics without a link never reaches Jev at all, and comes back `judged=False` with no
    scores. A message carrying both labels is dropped too, because it belongs to neither arm.

    The clean pool is split in two, so no clean message is reused between the spam arm and the
    harassment arm and the two results stay independent.
    """
    rng = random.Random(SEED)
    dropped = {"prefiltered": 0, "both_labels": 0}
    spam, harass, clean = [], [], []
    for it in _items():
        labels = set(it.get("labels") or [])
        if prefilter(Message(it["id"], it["text"])):
            dropped["prefiltered"] += 1
            continue
        if "spam" in labels and "harassment" in labels:
            dropped["both_labels"] += 1
            continue
        if "spam" in labels:
            spam.append(it)
        elif "harassment" in labels:
            harass.append(it)
        elif not labels:
            clean.append(it)
    for pool in (spam, harass, clean):
        rng.shuffle(pool)
    return {
        "spam": spam[:PER_POOL],
        "harassment": harass[:PER_POOL],
        "clean_vs_spam": clean[:PER_POOL],
        "clean_vs_harassment": clean[PER_POOL : PER_POOL * 2],
    }, dropped


def batches(condition: str) -> list[list[dict]]:
    """The batches for one condition, in the order they are asked.

    `pure` and `pure2` are the same batches; the point of the second is that nothing differs but the
    asking. `mixed` interleaves a positive pool with its own clean pool so every batch is about half
    each, which is the composition REPORT2 used.
    """
    p, _ = pools()
    out: list[list[dict]] = []
    if condition in ("pure", "pure2", "reordered", "reshuffled"):
        rng = random.Random(RESHUFFLE_SEED)
        order = random.Random(REORDER_SEED)
        for name in ("spam", "harassment", "clean_vs_spam", "clean_vs_harassment"):
            pool = list(p[name])
            if condition == "reshuffled":
                rng.shuffle(pool)
            chunks = [pool[i : i + BATCH] for i in range(0, len(pool), BATCH)]
            if condition == "reordered":
                for chunk in chunks:
                    order.shuffle(chunk)
            out += chunks
        return out
    if condition == "mixed":
        for pos, neg in (("spam", "clean_vs_spam"), ("harassment", "clean_vs_harassment")):
            merged = [x for pair in zip(p[pos], p[neg], strict=True) for x in pair]
            out += [merged[i : i + BATCH] for i in range(0, len(merged), BATCH)]
        return out
    raise SystemExit(f"unknown condition {condition!r}; use one of {', '.join(CONDITIONS)}")


def _done() -> set[tuple[str, str]]:
    if not OUT.exists():
        return set()
    return {(json.loads(line)["condition"], json.loads(line)["id"]) for line in OUT.open(encoding="utf-8")}


def ask(condition: str, limit: int | None = None) -> None:
    """Score one condition. `limit` caps the number of batches, which is what `pilot` uses."""
    OUT.parent.mkdir(exist_ok=True)
    done = _done()
    todo = [b for b in batches(condition) if any((condition, it["id"]) not in done for it in b)]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        print(f"{condition}: nothing left to ask")
        return

    # cache_ttl_s=0 is the whole experiment. `Judge.cache` is keyed by normalised text plus topic plus
    # category set, so with the default 24 hours the second and third conditions would come back
    # `reason="cache"` with a drift of exactly zero. That looks like a clean result and is not one.
    judge = Judge(cache_ttl_s=0)
    print(f"{condition}: {len(todo)} batch(es) of up to {BATCH}")
    t0 = time.time()
    with OUT.open("a", encoding="utf-8") as f:
        for n, chunk in enumerate(todo, 1):
            tok0 = judge.input_tokens
            t1 = time.perf_counter()
            verdicts = judge.judge([Message(it["id"], it["text"][:4000]) for it in chunk], CATS)
            ms = int((time.perf_counter() - t1) * 1000)
            toks = judge.input_tokens - tok0
            for it, v in zip(chunk, verdicts, strict=True):
                if v.reason == "cache":
                    raise SystemExit("a cached verdict reached the results; the experiment is void")
                if not v.judged:
                    raise SystemExit(f"{it['id']} came back unjudged ({v.reason}); it should have been dropped")
                f.write(json.dumps({
                    "condition": condition, "id": it["id"], "labels": it.get("labels") or [],
                    "scores": v.scores, "batch_n": len(chunk), "batch_tokens": toks, "batch_ms": ms,
                }) + "\n")
            f.flush()
            print(f"  {n}/{len(todo)}  {toks} tok  {ms} ms", end="\r")
    spent = judge.input_tokens * 0.042 / 1e6
    print(f"\n{condition}: {judge.judged_messages} judged, {judge.input_tokens} tokens, ${spent:.4f}, "
          f"{time.time() - t0:.0f}s")


def _rows() -> dict[str, dict[str, dict[str, float]]]:
    """{condition: {id: scores}}"""
    out: dict[str, dict[str, dict[str, float]]] = {c: {} for c in CONDITIONS}
    if not OUT.exists():
        return out
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        out.setdefault(r["condition"], {})[r["id"]] = r["scores"]
    return out


def analyse() -> None:
    """The tables. Per side and per category, never pooled: REPORT2's ALL row drifted +0.001 because
    opposite signs cancelled while the false-positive rate for one stratum more than doubled."""
    rows = _rows()
    p, _ = pools()
    sides = {
        ("spam", "positive"): p["spam"],
        ("spam", "clean"): p["clean_vs_spam"],
        ("harassment", "positive"): p["harassment"],
        ("harassment", "clean"): p["clean_vs_harassment"],
    }
    have = [c for c in CONDITIONS if rows.get(c)]
    if "pure" not in have:
        print("nothing to analyse yet: run `ask pure` first")
        return

    # The means are printed first and mean the least. They are here because REPORT2's ALL row is the
    # standing warning about reading them: it drifted +0.001 while one stratum's false-positive rate
    # went from 0.300 to 0.667 underneath it.
    print("Mean probability per condition. Read the flip tables below instead; these cancel.")
    print()
    print("| category | side | n | " + " | ".join(f"mean {c}" for c in have) + " |")
    print("|---" * (3 + len(have)) + "|")
    for (cat, side), pool in sides.items():
        ids = [i for i in (it["id"] for it in pool) if all(i in rows.get(c, {}) for c in have)]
        if not ids:
            continue
        m = {c: sum(rows[c][i][cat] for i in ids) / len(ids) for c in have}
        print(f"| {cat} | {side} | {len(ids)} | " + " | ".join(f"{m[c]:.3f}" for c in have) + " |")

    print()
    print("Messages crossing their shipping threshold, which is the number that decides the issue.")
    print("Read left to right: nothing, position, neighbours, composition. Each column changes one")
    print("more thing than the one before it.")
    print()
    print("| category | side | n | threshold | pure->pure2 (nothing changed) | pure->reordered (position) "
          "| pure->reshuffled (neighbours) | pure->mixed (composition) |")
    print("|---|---|---|---|---|---|---|---|")
    for (cat, side), pool in sides.items():
        th = THRESHOLD[cat]
        ids = [it["id"] for it in pool if all(it["id"] in rows.get(c, {}) for c in have)]
        if not ids:
            continue

        def flips(a: str, b: str, cat: str = cat, th: float = th, ids: list[str] = ids) -> str:
            if a not in have or b not in have:
                return "-"
            n = sum((rows[a][i][cat] >= th) != (rows[b][i][cat] >= th) for i in ids)
            return f"{n}/{len(ids)} ({n / len(ids):.1%})"

        print(f"| {cat} | {side} | {len(ids)} | {th} | {flips('pure', 'pure2')} | "
              f"{flips('pure', 'reordered')} | {flips('pure', 'reshuffled')} | {flips('pure', 'mixed')} |")

    print()
    print("Which way the flips go, pure -> mixed. `lost` is a message that was over the line and no")
    print("longer is; `gained` is one that crosses it only in the mixed batch.")
    print()
    print("| category | side | lost (falls under) | gained (rises over) | what it would mean in production |")
    print("|---|---|---|---|---|")
    meaning = {
        ("spam", "positive"): "spam that stops being deleted",
        ("spam", "clean"): "ordinary messages deleted as spam",
        ("harassment", "positive"): "harassment that stops being acted on",
        ("harassment", "clean"): "ordinary messages acted on as harassment",
    }
    for (cat, side), pool in sides.items():
        if "mixed" not in have:
            continue
        th = THRESHOLD[cat]
        ids = [it["id"] for it in pool if all(it["id"] in rows.get(c, {}) for c in have)]
        lost = sum(rows["pure"][i][cat] >= th > rows["mixed"][i][cat] for i in ids)
        gained = sum(rows["mixed"][i][cat] >= th > rows["pure"][i][cat] for i in ids)
        print(f"| {cat} | {side} | {lost} | {gained} | {meaning[(cat, side)]} |")
    print()
    print("A composition column only means something where it is larger than both columns to its left.")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "pools"
    if cmd == "pools":
        p, dropped = pools()
        for name, pool in p.items():
            print(f"{name:22s} {len(pool)}")
        print(f"dropped: {dropped}")
        for c in CONDITIONS:
            print(f"{c:6s} {len(batches(c))} batches")
    elif cmd == "pilot":
        for c in CONDITIONS:
            ask(c, limit=1)
    elif cmd == "ask":
        if len(argv) < 2:
            return int(bool(print(f"ask which? one of {', '.join(CONDITIONS)}")))
        ask(argv[1])
    elif cmd == "analyse":
        analyse()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
