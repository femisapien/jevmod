"""Does a `doxxing` or `minors` score depend on the batch it is judged in? JEV-62.

JEV-56 (`benchmark/BATCH_EFFECT.md`) found that for spam and harassment *which* messages share a
request moves a score, and *what kind* of messages they are does not. REPORT2 found the opposite for
`ai_generated`: composition carried the whole effect. The two reports reconciled that with a rule,
written to explain two data points: questions about the author or the world use the neighbours as
evidence, questions about the text do not. The rule predicts that `doxxing` (is this data real, is
this a private person) and `minors` (is a minor involved) are composition-sensitive. This file tests
that prediction, with the same design and the same statistics as JEV-56, at the shipped thresholds.

Two groups, each with a positive pool and a hard-negative pool:

    doxxing  150 synthetic positives, 150 synthetic hard negatives (`doxxing_items.py`: the
             labelled set has no doxxing rows), threshold 0.80
    minors   the 85 rows the labelled set marks `minors` (OpenAI moderation eval, S3), against 85
             rows marked `nsfw` and not `minors` (adult sexual content, which the category's
             `false` criterion excludes by name), threshold 0.70

Six conditions, the production question set, 25 messages per request where the condition batches:

    pure            every message in the batch from the same pool, in seeded pool order
    pure2           the identical batches again: the noise floor
    reshuffled      the same pool, regrouped: membership randomised, composition held
    mixed_shuffled  positives and hard negatives together, membership randomised: composition half
                    the other side. Against `reshuffled`, composition is the only difference
    diluted         five messages of one pool among twenty neutral chat comments (the clean YouTube
                    comments of the labelled set), positions shuffled. What a doxxing message meets
                    in a real channel: composition 80% unrelated. Against `reshuffled`, again
                    composition is the only difference, and a much larger one
    single          one message per request, `m0` holding the lead filler as it does in production
                    for a quiet channel with no history

The rule predicts that `mixed_shuffled` and `diluted` move positives (down: fewer doxxing
neighbours, less evidence) or hard negatives (up: an address among doxxing reads as doxxing) by more
than `reshuffled` does. JEV-56 found neither for spam and harassment.

    python -m benchmark.batch_doxxing_minors.doxxing_items    # free: writes doxxing.jsonl
    python -m benchmark.batch_doxxing_minors.run pools        # free: pools, drops, batch counts
    python -m benchmark.batch_doxxing_minors.run pilot        # paid, one batch per condition
    python -m benchmark.batch_doxxing_minors.run ask all      # paid, resumable, or one condition
    python -m benchmark.batch_doxxing_minors.run analyse      # free, from results.jsonl

The results hold ids and scores, never text: the `minors` rows are sexual content about minors from
a public moderation eval and are not reproduced anywhere in this folder. Their text stays in the
git-ignored `benchmark/data/items.jsonl` that `benchmark/prepare.py` builds.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import time
from math import sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark.batch_doxxing_minors import doxxing_items  # noqa: E402
from jevmod.core.policy import DEFAULT_ACTIONS, DEFAULT_THRESHOLDS  # noqa: E402
from jevmod.judge import CATEGORIES, Judge, Message, prefilter  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
OUT = Path(__file__).parent / "results.jsonl"

# The categories that ship on, exactly as `batch_effect.py` asks them, so the prompt is production's.
CATS = [c for c in CATEGORIES if DEFAULT_ACTIONS.get(c, "flag") != "off"]
BATCH = 25
DILUTE_TARGETS = 5  # per batch of 25 in `diluted`; the other 20 are neutral chat
USD_PER_M = 0.042   # list price per million input tokens, the figure every benchmark here uses

# Read from the policy rather than typed, so a change to the shipped line changes this measurement.
THRESHOLD = {"doxxing": DEFAULT_THRESHOLDS["doxxing"], "minors": DEFAULT_THRESHOLDS["minors"]}

SEED = 62
RESHUFFLE_SEED = 620
MIX_SEED = 6262
DILUTE_SEED = 6200
MINORS_N = 85
CONDITIONS = ("pure", "pure2", "reshuffled", "mixed_shuffled", "diluted", "single")
GROUPS = ("doxxing", "minors")
SIDES = ("positive", "hardneg")


def _labelled() -> list[dict]:
    return [json.loads(line) for line in (DATA / "items.jsonl").open(encoding="utf-8")]


def pools() -> tuple[dict[tuple[str, str], list[dict]], list[dict], dict[str, int]]:
    """{(group, side): items}, the neutral pool, and what was dropped building them."""
    rng = random.Random(SEED)
    dropped = {"prefiltered": 0}

    def ok(it: dict) -> bool:
        if prefilter(Message(it["id"], it["text"])):
            dropped["prefiltered"] += 1
            return False
        return True

    dox = [it for it in doxxing_items.load() if ok(it)]
    rows = _labelled()
    minors = [it for it in rows if "minors" in (it.get("labels") or []) and ok(it)]
    adult = [it for it in rows if "nsfw" in (it.get("labels") or []) and "minors" not in it["labels"] and ok(it)]
    # Chat-shaped neutral text: the YouTube comments the labelled set marks clean. Short, casual, and
    # far from both lines, which is what a doxxing message is surrounded by in a real channel.
    neutral = [it for it in rows if it["source"] == "youtube_spam" and not it.get("labels") and ok(it)]
    rng.shuffle(adult)
    out = {
        ("doxxing", "positive"): [it for it in dox if it["side"] == "positive"],
        ("doxxing", "hardneg"): [it for it in dox if it["side"] == "hardneg"],
        ("minors", "positive"): minors[:MINORS_N],
        ("minors", "hardneg"): adult[:MINORS_N],
    }
    for pool in out.values():
        rng.shuffle(pool)
    return out, neutral, dropped


def _chunks(items: list[dict]) -> list[list[dict]]:
    return [items[i : i + BATCH] for i in range(0, len(items), BATCH)]


def batches(condition: str) -> list[list[tuple[dict, bool]]]:
    """The requests for one condition. Each entry is (item, recorded): neutral fillers in `diluted`
    are judged, because that is the composition under test, and their scores are not recorded."""
    p, neutral, _ = pools()
    out: list[list[tuple[dict, bool]]] = []
    if condition in ("pure", "pure2", "reshuffled"):
        rng = random.Random(RESHUFFLE_SEED)
        for key in p:
            pool = list(p[key])
            if condition == "reshuffled":
                rng.shuffle(pool)
            out += [[(it, True) for it in c] for c in _chunks(pool)]
        return out
    if condition == "mixed_shuffled":
        mix = random.Random(MIX_SEED)
        for group in GROUPS:
            merged = p[(group, "positive")] + p[(group, "hardneg")]
            mix.shuffle(merged)
            out += [[(it, True) for it in c] for c in _chunks(merged)]
        return out
    if condition == "diluted":
        rng = random.Random(DILUTE_SEED)
        for key in p:
            pool = list(p[key])
            rng.shuffle(pool)
            for i in range(0, len(pool), DILUTE_TARGETS):
                batch = [(it, True) for it in pool[i : i + DILUTE_TARGETS]]
                batch += [(it, False) for it in rng.sample(neutral, BATCH - len(batch))]
                rng.shuffle(batch)
                out.append(batch)
        return out
    if condition == "single":
        return [[(it, True)] for key in p for it in p[key]]
    raise SystemExit(f"unknown condition {condition!r}; use one of {', '.join(CONDITIONS)}")


def batch_key(chunk: list[tuple[dict, bool]]) -> str:
    """The request's identity: the ids it held, in order. Stable across resumed runs."""
    return "|".join(it["id"] for it, _ in chunk)


def _side_of() -> dict[str, tuple[str, str]]:
    p, _, _ = pools()
    return {it["id"]: key for key, pool in p.items() for it in pool}


def _done() -> set[tuple[str, str]]:
    if not OUT.exists():
        return set()
    return {(r["condition"], r["id"]) for r in map(json.loads, OUT.open(encoding="utf-8"))}


def ask(condition: str, limit: int | None = None) -> float:
    """Score one condition; resumable. Returns dollars spent."""
    done = _done()
    side = _side_of()
    # A batch is asked whole or not at all: dropping the ids already scored would change the
    # composition of the request, which is the variable under test. A batch with every recorded id
    # present is skipped; a partly present one cannot happen, because a batch is written in one go.
    todo = [b for b in batches(condition) if any(rec and (condition, it["id"]) not in done for it, rec in b)]
    partial = [b for b in todo if any(rec and (condition, it["id"]) in done for it, rec in b)]
    if partial:
        raise SystemExit(f"{condition}: {len(partial)} batch(es) partly recorded; the results file is damaged")
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        print(f"{condition}: nothing left to ask")
        return 0.0
    # cache_ttl_s=0 is load-bearing: with the default a repeated text answers from the cache and the
    # drift comes out as exactly zero. The harness refuses a cached verdict rather than recording it.
    judge = Judge(cache_ttl_s=0)
    t0 = time.time()
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for n, chunk in enumerate(todo, 1):
            tok0 = judge.input_tokens
            verdicts = judge.judge([Message(it["id"], it["text"][:4000]) for it, _ in chunk], CATS)
            toks = judge.input_tokens - tok0
            lines = []
            for pos, ((it, rec), v) in enumerate(zip(chunk, verdicts, strict=True)):
                if v.reason == "cache":
                    raise SystemExit("a cached verdict reached the results; the experiment is void")
                if not v.judged:
                    raise SystemExit(f"{it['id']} came back unjudged ({v.reason}); it should have been dropped")
                if rec:
                    group, s = side[it["id"]]
                    lines.append(json.dumps({
                        "condition": condition, "group": group, "side": s, "id": it["id"],
                        "scores": v.scores, "batch_n": len(chunk), "pos": pos + 1, "batch_tokens": toks,
                        "req": f"{condition}:{batch_key(chunk)}",
                    }) + "\n")
            f.writelines(lines)
            f.flush()
            print(f"  {n}/{len(todo)}  {toks} tok", end="\r")
    spent = judge.input_tokens * USD_PER_M / 1e6
    print(f"\n{condition}: {len(todo)} requests, {judge.input_tokens} tokens, ${spent:.4f}, {time.time() - t0:.0f}s")
    return spent


def _rows() -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {c: {} for c in CONDITIONS}
    if not OUT.exists():
        return out
    for r in map(json.loads, OUT.open(encoding="utf-8")):
        if r["id"] in out[r["condition"]]:
            raise SystemExit(f"duplicate row {r['condition']}/{r['id']}; the results file is damaged")
        out[r["condition"]][r["id"]] = r["scores"]
    return out


# --- statistics, written out: scipy is not a dependency and a benchmark must not add one ---------

def _binom(k: int, n: int) -> float:
    """Two-sided exact binomial at p = 0.5, the McNemar and sign-test p-value."""
    if n == 0:
        return 1.0
    from math import comb
    probs = [comb(n, i) * 0.5 ** n for i in range(n + 1)]
    return min(1.0, sum(x for x in probs if x <= probs[k] + 1e-12))


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _clusters(ids: list, cluster_of: dict[str, str]) -> list[list]:
    """`ids` grouped by the unit that was sampled independently. An entry may be an id or a
    (tag, id) pair."""
    out: dict[str, list] = {}
    for x in ids:
        out.setdefault(cluster_of[x[1] if isinstance(x, tuple) else x], []).append(x)
    return list(out.values())


def _boot(clusters: list[list], stat, n: int = 4000, seed: int = 62) -> tuple[float, float]:
    """Percentile bootstrap, 95%, resampling whole clusters.

    The doxxing items are 16 templates per side with the slots filled, not 150 independent texts:
    ten messages from one template share their wording and, as the results show, their behaviour.
    Resampling items would treat them as ten pieces of evidence and give intervals far too narrow,
    so the unit resampled is the template. A `minors` row is its own cluster."""
    r = random.Random(seed)
    vals = []
    for _ in range(n):
        v = stat([x for _ in clusters for x in r.choice(clusters)])
        if v == v:  # a precision with nothing over the line in a resample is undefined, not zero
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _cluster_sign(clusters: list[list], diff: dict[str, float]) -> tuple[int, int]:
    """How many clusters moved up and down on average: the sign test at the independent unit."""
    means = [statistics.mean(diff[i] for i in c) for c in clusters]
    return sum(m > 0 for m in means), sum(m < 0 for m in means)


def _holm(tests: list[tuple[str, float]]) -> dict[str, float]:
    out, prev, m = {}, 0.0, len(tests)
    for k, (name, p) in enumerate(sorted(tests, key=lambda t: t[1])):
        prev = min(1.0, max(prev, (m - k) * p))
        out[name] = prev
    return out


def analyse() -> None:
    rows = _rows()
    p, _, dropped = pools()
    have = [c for c in CONDITIONS if rows[c]]
    if "pure" not in have:
        print("nothing to analyse yet: run `ask pure` first")
        return
    print(f"dropped by the pre-filter: {dropped['prefiltered']}")
    cluster_of = {it["id"]: (f"{it['side']}-t{it['template']}" if g == "doxxing" else it["id"])
                  for (g, _), pool in p.items() for it in pool}

    def ids_for(group: str, side: str, conds: list[str]) -> list[str]:
        return [it["id"] for it in p[(group, side)] if all(it["id"] in rows[c] for c in conds)]

    def hit(c: str, i: str, g: str) -> bool:
        return rows[c][i][g] >= THRESHOLD[g]

    print("\n## Mean score, and the share over the shipped line with its 95% Wilson interval\n")
    print("Positive side: the share over the line is recall. Hard-negative side: it is the false-positive rate.\n")
    print("| group | side | n | " + " | ".join(have) + " |")
    print("|---" * (3 + len(have)) + "|")
    for g in GROUPS:
        for s in SIDES:
            ids = ids_for(g, s, have)
            cells = []
            for c in have:
                k = sum(hit(c, i, g) for i in ids)
                lo, hi = _wilson(k, len(ids))
                cells.append(f"{statistics.mean(rows[c][i][g] for i in ids):.3f} / "
                             f"{100 * k / len(ids):.1f}% [{100 * lo:.0f}, {100 * hi:.0f}]")
            print(f"| {g} | {s} | {len(ids)} | " + " | ".join(cells) + " |")

    print("\n## Precision at the pools' own 1:1 ratio, bootstrap 95%\n")
    print("Not a production precision: the negatives are the hardest ones there are and the base rate is")
    print("50%. It is here so a condition that buys recall with false positives shows it.\n")
    print("| group | " + " | ".join(have) + " |")
    print("|---" * (1 + len(have)) + "|")
    for g in GROUPS:
        pos, neg = ids_for(g, "positive", have), ids_for(g, "hardneg", have)
        both = [("p", i) for i in pos] + [("n", i) for i in neg]
        cells = []
        for c in have:
            def prec(sample, c=c, g=g):
                tp = sum(1 for side, i in sample if side == "p" and hit(c, i, g))
                fp = sum(1 for side, i in sample if side == "n" and hit(c, i, g))
                return tp / (tp + fp) if tp + fp else float("nan")
            lo, hi = _boot(_clusters(both, cluster_of), prec)
            cells.append(f"{prec(both):.3f} [{lo:.2f}, {hi:.2f}]")
        print(f"| {g} | " + " | ".join(cells) + " |")

    # Threshold crossings against `pure`, each manipulation against the `pure2` floor. Holm over the
    # whole family, as JEV-56 did: a count that does not survive it is not a finding.
    manip = [c for c in have if c not in ("pure", "pure2")]
    if "pure2" in have:
        print("\n## Crossings of the shipped line against `pure`, McNemar against the `pure2` floor, Holm\n")
        tests, meta = [], {}
        for g in GROUPS:
            for s in SIDES:
                ids = ids_for(g, s, have)
                base = [hit("pure", i, g) != hit("pure2", i, g) for i in ids]
                for c in manip:
                    man = [hit("pure", i, g) != hit(c, i, g) for i in ids]
                    b = sum(1 for x, y in zip(man, base, strict=True) if x and not y)
                    d = sum(1 for x, y in zip(man, base, strict=True) if y and not x)
                    name = f"{g}/{s}/{c}"
                    tests.append((name, _binom(b, b + d)))
                    meta[name] = (len(ids), sum(man), sum(base))
        holm = _holm(tests)
        print("| comparison | n | flips vs floor | raw p | Holm p |")
        print("|---|---|---|---|---|")
        for name, raw in sorted(tests, key=lambda t: t[1]):
            n, f, fl = meta[name]
            print(f"| {name} | {n} | {f} vs {fl} | {raw:.4f} | {holm[name]:.3f}"
                  f"{' **survives**' if holm[name] < 0.05 else ''} |")

    # The tests of the rule. Every contrast is against `reshuffled`, the arm with membership
    # randomised and composition held, so composition is the only difference. Two measures: the sign
    # test on paired scores (does the distribution shift at all, the test that found spam's +0.19)
    # and the paired difference in the share over the line, with a bootstrap interval (does the shift
    # change a decision).
    contrasts = [c for c in ("mixed_shuffled", "diluted", "single") if c in have and "reshuffled" in have]
    if contrasts:
        print("\n## Composition against `reshuffled`: score shift and decision shift, Holm over the family\n")
        print("`single` is not a composition contrast but a batch-against-none one; it is in the family so")
        print("the correction covers it.\n")
        tests, meta2 = [], {}
        for g in GROUPS:
            for s in SIDES:
                for c in contrasts:
                    ids = ids_for(g, s, ["reshuffled", c])
                    diff = {i: rows[c][i][g] - rows["reshuffled"][i][g] for i in ids}
                    cl = _clusters(ids, cluster_of)
                    up, down = sum(d > 0 for d in diff.values()), sum(d < 0 for d in diff.values())
                    cup, cdown = _cluster_sign(cl, diff)
                    rate = lambda sample, c=c, g=g: (  # noqa: E731
                        sum(hit(c, i, g) for i in sample) - sum(hit("reshuffled", i, g) for i in sample)) / len(sample)
                    lo, hi = _boot(cl, rate)
                    mlo, mhi = _boot(cl, lambda sample, c=c, g=g: statistics.mean(
                        rows[c][i][g] - rows["reshuffled"][i][g] for i in sample))
                    name = f"{g}/{s}/{c}"
                    # The p-value that enters the family is the one at the independent unit: per
                    # template for doxxing, per item for minors (where the two are the same).
                    tests.append((name, _binom(cup, cup + cdown)))
                    meta2[name] = (len(ids), len(cl), up, down, cup, cdown, statistics.mean(diff.values()),
                                   mlo, mhi, rate(ids), lo, hi)
        holm = _holm(tests)
        print("Items up/down is descriptive. The sign p is computed on clusters (templates for doxxing, rows")
        print("for minors), and intervals resample clusters.\n")
        print("| contrast | items | clusters | items up/down | clusters up/down | sign p | Holm p "
              "| mean shift [95%] | share over line, change [95%] |")
        print("|---|---|---|---|---|---|---|---|---|")
        for name, raw in tests:
            n, k, up, down, cup, cdown, m, mlo, mhi, dr, lo, hi = meta2[name]
            print(f"| {name} | {n} | {k} | {up}/{down} | {cup}/{cdown} | {raw:.4f} | {holm[name]:.3f}"
                  f"{' **survives**' if holm[name] < 0.05 else ''} | {m:+.3f} [{mlo:+.3f}, {mhi:+.3f}] | "
                  f"{100 * dr:+.1f} pts [{100 * lo:+.1f}, {100 * hi:+.1f}] |")

    print("\n## Absolute movement against `pure`\n")
    print("| group | side | condition | mean | p95 | max |")
    print("|---|---|---|---|---|---|")
    for g in GROUPS:
        for s in SIDES:
            ids = ids_for(g, s, have)
            for c in [c for c in have if c != "pure"]:
                d = sorted(abs(rows[c][i][g] - rows["pure"][i][g]) for i in ids)
                print(f"| {g} | {s} | {c} | {statistics.mean(d):.3f} | {d[int(0.95 * (len(d) - 1))]:.3f} | {d[-1]:.3f} |")

    if OUT.exists():
        # batch_tokens repeats on every row of its request; `req` names the request, so each is counted once.
        reqs = {r["req"]: r["batch_tokens"] for r in map(json.loads, OUT.open(encoding="utf-8"))}
        tokens = sum(reqs.values())
        print(f"\n{len(reqs)} requests, {tokens} input tokens, ${tokens * USD_PER_M / 1e6:.4f}")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "pools"
    if cmd == "pools":
        p, neutral, dropped = pools()
        for key, pool in p.items():
            print(f"{'/'.join(key):20s} {len(pool)}")
        print(f"{'neutral':20s} {len(neutral)}")
        print(f"dropped: {dropped}")
        for c in CONDITIONS:
            b = batches(c)
            print(f"{c:15s} {len(b)} requests, {sum(len(x) for x in b)} judged")
    elif cmd == "pilot":
        total = sum(ask(c, limit=1) for c in CONDITIONS)
        print(f"pilot: ${total:.4f}")
    elif cmd == "ask":
        which = CONDITIONS if len(argv) < 2 or argv[1] == "all" else (argv[1],)
        total = sum(ask(c) for c in which)
        print(f"total this run: ${total:.4f}")
    elif cmd == "analyse":
        analyse()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
