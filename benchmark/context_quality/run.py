"""Does the conversation window make verdicts better, worse or no different, category by category?

JEV-18. `benchmark/EVAL.md` measured the window on `data/items.jsonl`, whose rows have no
conversation, so its "context" was neighbouring rows and it could only show that the window is not
inert. There is still no labelled set of real conversations (JEV-7 and JEV-11 own that). This run
uses the next best thing and says so: **cases written for the purpose, where the earlier messages
decide what the last one means**, labelled before anything was sent to the model.

**The data** (`data/<category>.jsonl`, one file per enabled category, 40 rows each):

* 15 **pairs** per category. Both halves end on a byte-identical closing line, written to be
  ambiguous alone; one lead-up makes it a violation of that category (`pair_pos`), the other makes it
  clearly innocent (`pair_neg`). Scored alone, both halves are the same text, so without the window
  the engine can get at most one of the two right at any threshold, repeat noise aside. This is where
  the window can help, and it is the upper end of what it can buy, not its average on real traffic.
* 5 **control_pos** per category: a line that violates on its own after ordinary unrelated chat. Asks
  whether a benign neighbourhood talks the model out of a true positive.
* 5 **control_neg** per category: an innocent line after other people violating the category. Asks
  whether a bad neighbourhood makes an innocent message look guilty. These two are where the window
  can hurt.

The label is what a moderator reading the whole conversation would decide about the closing line,
under that category's criteria in `jevmod/categories.json`. The same label scores every arm: the
question is how well the engine moderates the message as it was actually said.

**The arms**, every row judged in all four, two repeats each, in a shuffled order per row:

* `off`: the message alone. A fresh `ModerationService` with an empty window, so `m0` holds the
  filler and the message sits at `m1`. What production does with context off.
* `ctx_pad`: **what ships**. The lead-up is written into the service's `ConversationBuffer`, the
  service attaches the window through `assemble` and, the batch being one message, pads the request
  with the same window (`PAD_BATCH` on).
* `ctx`: the same with `PAD_BATCH` off: the `context` field only, the filler at `m0`. Separates what
  the `context` field buys from what padding buys (JEV-19's open question, on these rows only).
* `ctx_spk`: exploratory, not shipped. The `context` field with each entry prefixed by a speaker
  pseudonym, `[author]` for the judged message's own author and `[A]`, `[B]` ... for the others in
  order of appearance: the shape JEV-19 decided and no engine sends yet. Judged through `Judge`
  directly with no padding, so it compares with `ctx`.

**Pre-registered, written before the paid run** (the commit adding the data and this file precedes
the commit adding `results/`; `results/raw.jsonl` records the data's sha256):

1. Detection is the row's own category at or over its shipped threshold (`DEFAULT_THRESHOLDS`).
   Recall over the `label: true` rows, false-positive rate over the `label: false` rows, per
   category and pooled, per arm. Each row's score is the mean of its two repeats; 95% intervals by a
   bootstrap over scenarios (a pair is one scenario, so its two halves move together), 2,000
   resamples, seed fixed.
2. The primary comparison is `off` against `ctx_pad`. Context "helps" a category when the
   bootstrap interval of (recall gain minus FPR gain) excludes zero on the positive side, "hurts" when
   it excludes zero on the negative side, and otherwise the sample cannot tell. The paired McNemar
   exact test on per-row correctness is reported beside it.
3. Thresholds are retuned only if, for a category under `ctx_pad`, a threshold in 0.50 to 0.99
   chosen on odd-numbered scenarios improves recall minus FPR by at least 0.10 over the shipped one
   on even-numbered scenarios, **and** the same holds with the halves swapped. The prevalence here is
   50/50 by construction, which is not production's, so a threshold that passes is still checked
   against `tests/data/redteam.csv` before it ships.
4. Nothing is dropped after the run. A row the blind labeller disagreed with stays in the primary
   numbers and is reported separately (`--agreed-only` recomputes without them).

    python -m benchmark.context_quality.run check    # free: schema, pairs, lengths, hash
    python -m benchmark.context_quality.run blind    # free: writes the unlabelled file for the blind labeller
    python -m benchmark.context_quality.run ask      # paid, about $0.30, resumable, prints the running cost
    python -m benchmark.context_quality.run report   # free, every table in REPORT.md
    python -m benchmark.context_quality.run repeat_probe   # paid, under a cent; added after the run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from math import comb
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: E402

import jevmod.core.service as service_mod  # noqa: E402
from jevmod.core.context import ConversationBuffer, assemble  # noqa: E402
from jevmod.core.policy import DEFAULT_THRESHOLDS, Policy  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import Judge, Message, prefilter  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "results" / "raw.jsonl"
BLIND = HERE / "results" / "blind_input.jsonl"
BLIND_LABELS = HERE / "results" / "blind_labels.jsonl"
CATS = ("spam", "scam", "harassment", "nsfw", "selfharm", "doxxing", "minors")
KINDS = ("pair_pos", "pair_neg", "control_pos", "control_neg")
ARMS = ("off", "ctx", "ctx_pad", "ctx_spk")
REPEATS = 2
SEED = 20260928
USD_PER_M = 0.042  # list price per million input tokens, the figure every other benchmark here uses
BUDGET_TOKENS = 40_000_000  # abort past this, about $1.70
TENANT = "bench"
BOOT = 2000


def rows() -> list[dict[str, Any]]:
    out = []
    for cat in CATS:
        for line in (DATA / f"{cat}.jsonl").open(encoding="utf-8"):
            if line.strip():
                out.append(json.loads(line))
    return out


def data_hash() -> str:
    h = hashlib.sha256()
    for cat in CATS:
        h.update((DATA / f"{cat}.jsonl").read_bytes())
    return h.hexdigest()


def check() -> int:
    """Everything that can be wrong with the data without asking the model."""
    rs = rows()
    bad: list[str] = []
    ids = [r["id"] for r in rs]
    if len(ids) != len(set(ids)):
        bad.append("duplicate ids")
    by_scn: dict[str, list[dict[str, Any]]] = {}
    for r in rs:
        by_scn.setdefault(r["scenario"], []).append(r)
        if r["category"] not in CATS or r["kind"] not in KINDS:
            bad.append(f"{r['id']}: category or kind")
        if r["label"] != r["kind"].endswith("pos"):
            bad.append(f"{r['id']}: label does not match kind")
        if not 4 <= len(r["lead"]) <= 9:
            bad.append(f"{r['id']}: lead has {len(r['lead'])} messages")
        # A note, not a failure: the check used to count characters with `len`, which let "Get out."
        # (six letters) through while the engine's pre-filter skips it. The rows were frozen before that
        # was noticed, so they stay, and the pre-filter's verdict is what every arm got.
        skip = prefilter(Message(r["id"], r["closing"]["text"]))
        if skip:
            print(f"NOTE {r['id']}: the pre-filter skips the closing ({skip}); every arm scores it 0")
    for scn, rr in by_scn.items():
        if rr[0]["kind"].startswith("pair"):
            if sorted(r["kind"] for r in rr) != ["pair_neg", "pair_pos"]:
                bad.append(f"{scn}: not one pos and one neg")
            elif rr[0]["closing"] != rr[1]["closing"] or rr[0]["topic"] != rr[1]["topic"]:
                bad.append(f"{scn}: closing or topic differs between the halves")
        elif len(rr) != 1:
            bad.append(f"{scn}: control scenario with {len(rr)} rows")
    for cat in CATS:
        n = {k: sum(1 for r in rs if r["category"] == cat and r["kind"] == k) for k in KINDS}
        print(cat, n)
    print(f"{len(rs)} rows, data sha256 {data_hash()}")
    for b in bad:
        print("BAD", b)
    return 1 if bad else 0


def blind() -> None:
    """The file a second labeller reads: conversation and closing line, no label, no kind, no reason,
    ids replaced and order shuffled, so the author's intent cannot be read off the row."""
    rs = rows()
    rng = random.Random(SEED + 7)
    rng.shuffle(rs)
    key = {}
    with BLIND.open("w", encoding="utf-8") as f:
        for k, r in enumerate(rs):
            bid = f"b{k:03d}"
            key[bid] = r["id"]
            f.write(json.dumps({"bid": bid, "category": r["category"], "topic": r["topic"],
                                "lead": r["lead"], "closing": r["closing"]}, ensure_ascii=False) + "\n")
    (HERE / "results" / "blind_key.json").write_text(json.dumps(key, indent=0), encoding="utf-8")
    print(f"wrote {len(rs)} rows to {BLIND}")


class Recorder:
    """The real client, with each call's reported usage written down. `Judge` only calls
    `system_one`."""

    def __init__(self) -> None:
        self.inner = TypeSafeClient(
            api_key=get_api_key(),
            retry=RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                              http_statuses={429, 500, 502, 503, 504, 529}),
            timeout=30.0,
        )
        self.calls: list[dict[str, Any]] = []

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        t = time.perf_counter()
        resp = self.inner.system_one(state=state, questions=questions)
        usage = getattr(resp, "usage", None)
        msgs = state["messages"]
        self.calls.append({
            "ms": round((time.perf_counter() - t) * 1000, 1),
            "input_tokens": getattr(usage, "input_tokens", None),
            "positions": len(msgs),
            "context_entries": sum(len(m.get("context", {})) for m in msgs.values()),
        })
        return resp


def speakers(r: dict[str, Any]) -> tuple[str, ...]:
    """The lead as `[A] text`, the closing's own author as `[author]`. The judged text is excluded
    exactly as `window_for(exclude=...)` excludes it, so this arm differs from `ctx` in the labels
    only."""
    own = r["closing"]["author"]
    names: dict[str, str] = {}
    out = []
    for m in r["lead"]:
        if m["text"] == r["closing"]["text"]:
            continue
        tag = "author" if m["author"] == own else names.setdefault(m["author"], chr(ord("A") + len(names)))
        out.append(f"[{tag}] {m['text']}")
    return assemble(tuple(out))


def one(rec: Recorder, r: dict[str, Any], arm: str) -> dict[str, Any]:
    cats = Policy().enabled_categories()
    before = len(rec.calls)
    closing = r["closing"]["text"]
    if arm == "ctx_spk":
        judge = Judge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
        m = Message(r["id"], closing, channel_topic=r["topic"], context=speakers(r))
        v = judge.judge([m], cats)[0]
        scores, judged, reason, ctx_kept = v.scores, v.judged, v.reason, len(m.context)
    else:
        store = Store(":memory:")
        store.set_plan(TENANT, "unlimited")
        svc = ModerationService(store, judge=Judge(client=rec, cache_ttl_s=0))  # type: ignore[arg-type]
        svc.context = ConversationBuffer()
        if arm != "off":
            for msg in r["lead"]:
                svc.context.add((TENANT, ""), msg["text"])
        m = Message(r["id"], closing, author=r["closing"]["author"], channel_topic=r["topic"])
        service_mod.PAD_BATCH = arm == "ctx_pad"
        try:
            d = svc.moderate(TENANT, [m])[0]
        finally:
            service_mod.PAD_BATCH = True
        scores, judged, reason, ctx_kept = d.scores, d.judged, d.reason, len(m.context)
    calls = rec.calls[before:]
    return {
        "id": r["id"], "arm": arm, "scores": {k: round(v, 5) for k, v in scores.items()},
        "judged": judged, "reason": reason, "context_kept": ctx_kept,
        "positions": sum(c["positions"] for c in calls),
        "input_tokens": sum(c["input_tokens"] or 0 for c in calls), "requests": len(calls),
        "ms": sum(c["ms"] for c in calls),
    }


def ask() -> None:
    rs = rows()
    sha = data_hash()
    OUT.parent.mkdir(exist_ok=True)
    done: set[tuple[str, str, int]] = set()
    spent = 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            x = json.loads(line)
            if x["data_sha256"] != sha:
                raise SystemExit("results/raw.jsonl was produced from different data; refusing to mix")
            done.add((x["id"], x["arm"], x["repeat"]))
            spent += x["input_tokens"]
    rng = random.Random(SEED)
    rec = Recorder()
    todo = [(r, rep) for rep in range(REPEATS) for r in rs]
    with OUT.open("a", encoding="utf-8") as f:
        for k, (r, rep) in enumerate(todo, 1):
            order = list(ARMS)
            rng.shuffle(order)  # drawn even when skipped, so a resumed run keeps the same order
            for arm in order:
                if (r["id"], arm, rep) in done:
                    continue
                x = one(rec, r, arm)
                x.update(repeat=rep, data_sha256=sha, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
                f.write(json.dumps(x) + "\n")
                f.flush()
                spent += x["input_tokens"]
                if spent > BUDGET_TOKENS:
                    print(f"\nstopped: {spent:,} input tokens is past the budget")
                    return
            print(f"  {k}/{len(todo)}  {spent:,} tok  ${spent * USD_PER_M / 1e6:.4f}", end="\r")
    print(f"\ndone: {spent:,} input tokens, ${spent * USD_PER_M / 1e6:.4f}")


# ---------------------------------------------------------------- report


def _load(agreed_only: bool) -> tuple[list[dict[str, Any]], dict[tuple[str, str], float], list[dict[str, Any]]]:
    rs = rows()
    raw = [json.loads(line) for line in OUT.open(encoding="utf-8")]
    if agreed_only:
        agree = _blind_agreement(rs, quiet=True)
        rs = [r for r in rs if agree.get(r["id"], True)]
    cat_of = {r["id"]: r["category"] for r in rs}
    per: dict[tuple[str, str], list[float]] = {}
    for x in raw:
        if x["id"] in cat_of:
            per.setdefault((x["id"], x["arm"]), []).append(x["scores"].get(cat_of[x["id"]], 0.0))
    score = {k: statistics.mean(v) for k, v in per.items()}
    return rs, score, raw


def _rates(rs: list[dict[str, Any]], score: dict[tuple[str, str], float], arm: str,
           thr: dict[str, float] | None = None) -> tuple[float, float, int, int]:
    thr = thr or DEFAULT_THRESHOLDS
    pos = [r for r in rs if r["label"]]
    neg = [r for r in rs if not r["label"]]
    tp = sum(score[(r["id"], arm)] >= thr[r["category"]] for r in pos)
    fp = sum(score[(r["id"], arm)] >= thr[r["category"]] for r in neg)
    return (tp / len(pos) if pos else float("nan"), fp / len(neg) if neg else float("nan"), len(pos), len(neg))


def _boot(rs: list[dict[str, Any]], fn: Any, seed: int = SEED) -> tuple[float, float]:
    """Percentile interval of `fn(rows)`, resampling scenarios with replacement."""
    scn: dict[str, list[dict[str, Any]]] = {}
    for r in rs:
        scn.setdefault(r["scenario"], []).append(r)
    keys = sorted(scn)
    rng = random.Random(seed)
    vals = []
    for _ in range(BOOT):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in scn[k]]
        v = fn(sample)
        if v == v:  # drop NaN (a resample with no positives or no negatives)
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def _auroc(rs: list[dict[str, Any]], score: dict[tuple[str, str], float], arm: str) -> float:
    pos = [score[(r["id"], arm)] for r in rs if r["label"]]
    neg = [score[(r["id"], arm)] for r in rs if not r["label"]]
    if not pos or not neg:
        return float("nan")
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


def _fmt(x: float) -> str:
    return f"{100 * x:.0f}%"


def _blind_agreement(rs: list[dict[str, Any]], quiet: bool = False) -> dict[str, bool]:
    if not BLIND_LABELS.exists():
        return {}
    key = json.loads((HERE / "results" / "blind_key.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rs}
    out = {}
    for line in BLIND_LABELS.open(encoding="utf-8"):
        if line.strip():
            x = json.loads(line)
            rid = key[x["bid"]]
            if rid in by_id:
                out[rid] = bool(x["violates"]) == by_id[rid]["label"]
    if not quiet:
        print(f"blind labeller: {len(out)} rows labelled, agrees with the author on {sum(out.values())} "
              f"({_fmt(sum(out.values()) / max(1, len(out)))})")
        for kind in KINDS:
            ks = [r["id"] for r in rs if r["kind"] == kind and r["id"] in out]
            print(f"  {kind}: {sum(out[i] for i in ks)} of {len(ks)}")
        for rid, ok in sorted(out.items()):
            if not ok:
                print(f"  disagrees: {rid}")
    return out


def report(agreed_only: bool) -> None:
    rs, score, raw = _load(agreed_only)
    print(f"{len(rs)} rows, {len(raw)} judgements, data sha256 {raw[0]['data_sha256']}")
    bad = [x for x in raw if not x["judged"]]
    print(f"not judged: {len(bad)} {sorted({x['reason'] for x in bad})}\n")
    if not agreed_only:
        _blind_agreement(rows())
        print()

    groups = [(c, [r for r in rs if r["category"] == c]) for c in CATS] + [("all", rs)]

    print("## Recall and false-positive rate at the shipped thresholds, per arm\n")
    print("| category | thr | arm | recall | 95% CI | FPR | 95% CI | AUROC |")
    print("|---|---|---|---|---|---|---|---|")
    for name, g in groups:
        thr = DEFAULT_THRESHOLDS.get(name, float("nan"))
        for arm in ARMS:
            rec, fpr, npos, nneg = _rates(g, score, arm)
            rlo, rhi = _boot(g, lambda s, a=arm: _rates(s, score, a)[0])
            flo, fhi = _boot(g, lambda s, a=arm: _rates(s, score, a)[1])
            print(f"| {name} | {thr} | {arm} | {_fmt(rec)} of {npos} | {100 * rlo:.0f} to {100 * rhi:.0f}"
                  f" | {_fmt(fpr)} of {nneg} | {100 * flo:.0f} to {100 * fhi:.0f} | {_auroc(g, score, arm):.3f} |")

    print("\n## Context against no context, paired, per category\n")
    print("Gain = (recall with minus recall without) minus (FPR with minus FPR without), in points; "
          "McNemar on per-row correctness.\n")
    for other in ("ctx_pad", "ctx", "ctx_spk"):
        print(f"### `{other}` against `off`\n")
        print("| category | recall change | FPR change | gain | 95% CI of gain | rows right only with | "
              "only without | McNemar p | verdict |")
        print("|---|---|---|---|---|---|---|---|---|")
        for name, g in groups:
            def gain(s: list[dict[str, Any]], o: str = other) -> float:
                r1, f1, _, _ = _rates(s, score, o)
                r0, f0, _, _ = _rates(s, score, "off")
                return (r1 - r0) - (f1 - f0)
            r1, f1, _, _ = _rates(g, score, other)
            r0, f0, _, _ = _rates(g, score, "off")
            lo, hi = _boot(g, gain)

            def right(r: dict[str, Any], arm: str) -> bool:
                return (score[(r["id"], arm)] >= DEFAULT_THRESHOLDS[r["category"]]) == r["label"]
            b = sum(right(r, other) and not right(r, "off") for r in g)
            c = sum(right(r, "off") and not right(r, other) for r in g)
            verdict = "helps" if lo > 0 else "hurts" if hi < 0 else "cannot tell"
            print(f"| {name} | {100*(r1-r0):+.0f} | {100*(f1-f0):+.0f} | {100*gain(g):+.0f} | "
                  f"{100*lo:+.0f} to {100*hi:+.0f} | {b} | {c} | {_mcnemar(b, c):.3g} | {verdict} |")
        print()

    print("## By kind of row, pooled over categories (rate at or over the shipped threshold)\n")
    print("| kind | rows | " + " | ".join(ARMS) + " |")
    print("|---|---|" + "---|" * len(ARMS))
    for kind in KINDS:
        k = [r for r in rs if r["kind"] == kind]
        cells = []
        for arm in ARMS:
            hit = sum(score[(r["id"], arm)] >= DEFAULT_THRESHOLDS[r["category"]] for r in k)
            cells.append(f"{hit} ({_fmt(hit / len(k))})")
        print(f"| {kind} | {len(k)} | " + " | ".join(cells) + " |")

    print("\n## Pairs: both halves right\n")
    print("| category | " + " | ".join(ARMS) + " |")
    print("|---|" + "---|" * len(ARMS))
    for name, g in groups:
        scn: dict[str, list[dict[str, Any]]] = {}
        for r in g:
            if r["kind"].startswith("pair"):
                scn.setdefault(r["scenario"], []).append(r)
        full = [v for v in scn.values() if len(v) == 2]
        cells = []
        for arm in ARMS:
            ok = sum(all((score[(r["id"], arm)] >= DEFAULT_THRESHOLDS[r["category"]]) == r["label"] for r in v)
                     for v in full)
            cells.append(f"{ok} of {len(full)}")
        print(f"| {name} | " + " | ".join(cells) + " |")

    print("\n## Mean score of the row's category, positives and negatives\n")
    print("| category | " + " | ".join(f"{a} pos | {a} neg" for a in ARMS) + " |")
    print("|---|" + "---|" * (2 * len(ARMS)))
    for name, g in groups:
        cells = []
        for arm in ARMS:
            for lab in (True, False):
                v = [score[(r["id"], arm)] for r in g if r["label"] == lab]
                cells.append(f"{statistics.mean(v):.2f}")
        print(f"| {name} | " + " | ".join(cells) + " |")

    print("\n## Any category flagged on a negative row (other categories count too)\n")
    by_id = {r["id"]: r for r in rs}
    means: dict[tuple[str, str], dict[str, list[float]]] = {}
    for x in raw:
        if x["id"] in by_id:
            d = means.setdefault((x["id"], x["arm"]), {})
            for c, v in x["scores"].items():
                d.setdefault(c, []).append(v)
    print("| arm | negatives with any category over its threshold | of which another category |")
    print("|---|---|---|")
    negs = [r for r in rs if not r["label"]]
    for arm in ARMS:
        anyhit = other = 0
        for r in negs:
            sc = {c: statistics.mean(v) for c, v in means[(r["id"], arm)].items()}
            over = [c for c, v in sc.items() if v >= DEFAULT_THRESHOLDS.get(c, 2)]
            anyhit += bool(over)
            other += bool([c for c in over if c != r["category"]])
        print(f"| {arm} | {anyhit} of {len(negs)} ({_fmt(anyhit / len(negs))}) | {other} |")

    print("\n## Repeat noise: rows whose verdict flips between the two repeats\n")
    rep: dict[tuple[str, str], list[float]] = {}
    for x in raw:
        if x["id"] in by_id:
            rep.setdefault((x["id"], x["arm"]), []).append(x["scores"].get(by_id[x["id"]]["category"], 0.0))
    print("| arm | flips | mean abs difference |")
    print("|---|---|---|")
    for arm in ARMS:
        pairs = [v for (i, a), v in rep.items() if a == arm and len(v) == 2]
        flips = sum((v[0] >= DEFAULT_THRESHOLDS[by_id[i]["category"]]) != (v[1] >= DEFAULT_THRESHOLDS[by_id[i]["category"]])
                    for (i, a), v in rep.items() if a == arm and len(v) == 2)
        print(f"| {arm} | {flips} of {len(pairs)} | {statistics.mean(abs(v[0] - v[1]) for v in pairs):.3f} |")

    print("\n## Thresholds: the pre-registered cross-half check, on `ctx_pad`\n")
    print("| category | shipped | chosen on odd | J gain on even | chosen on even | J gain on odd | retune? |")
    print("|---|---|---|---|---|---|---|")
    grid = [round(0.50 + 0.01 * k, 2) for k in range(50)]
    for c in CATS:
        g = [r for r in rs if r["category"] == c]
        half = {0: [r for r in g if int(r["scenario"].rsplit("-", 1)[1][1:]) % 2 == 1],
                1: [r for r in g if int(r["scenario"].rsplit("-", 1)[1][1:]) % 2 == 0]}

        def j(s: list[dict[str, Any]], t: float, cat: str = c) -> float:
            rr, ff, _, _ = _rates(s, score, "ctx_pad", {**DEFAULT_THRESHOLDS, cat: t})
            return rr - ff
        cells = []
        ok = True
        for a, b in ((0, 1), (1, 0)):
            best = max(grid, key=lambda t, s=half[a]: (j(s, t), -abs(t - DEFAULT_THRESHOLDS[c])))
            gain = j(half[b], best) - j(half[b], DEFAULT_THRESHOLDS[c])
            ok = ok and gain >= 0.10
            cells += [f"{best:.2f}", f"{100 * gain:+.0f}"]
        print(f"| {c} | {DEFAULT_THRESHOLDS[c]} | " + " | ".join(cells) + f" | {'yes' if ok else 'no'} |")

    print("\n## Cost, billed input tokens per judged message\n")
    print("| arm | tokens per message | x off | $ per 1K | positions per request | context entries kept |")
    print("|---|---|---|---|---|---|")
    base = None
    for arm in ARMS:
        xs = [x for x in raw if x["arm"] == arm and x["id"] in by_id]
        tok = statistics.mean(x["input_tokens"] for x in xs)
        base = base or tok
        pos = statistics.mean(x["positions"] / max(1, x["requests"]) for x in xs)
        kept = statistics.mean(x["context_kept"] for x in xs)
        print(f"| {arm} | {tok:,.0f} | {tok / base:.2f}x | ${tok * USD_PER_M / 1e3:.3f} | {pos:.1f} | {kept:.1f} |")
    total = sum(x["input_tokens"] for x in raw)
    print(f"\nwhole run: {total:,} input tokens, ${total * USD_PER_M / 1e6:.3f}")


PROBE = HERE / "results" / "repeat_probe.jsonl"


def repeat_probe() -> None:
    """Added after the run, on a red-team finding, and reported as such. The service drops from the window
    any line identical to the one being judged (`window_for(exclude=...)`, and the padding filter), so a row
    whose evidence is that the same offer was already posted word for word is judged with that evidence
    removed. This judges exactly those rows once more with the repeats left in: `Judge` directly, the whole
    lead-up as `context` through `assemble`, no padding, two repeats. Compare with the `ctx` arm."""
    rs = [r for r in rows() if any(m["text"] == r["closing"]["text"] for m in r["lead"])]
    rec = Recorder()
    cats = Policy().enabled_categories()
    with PROBE.open("w", encoding="utf-8") as f:
        for r in rs:
            for rep in range(REPEATS):
                judge = Judge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
                ctx = assemble(tuple(m["text"] for m in r["lead"]))
                m = Message(r["id"], r["closing"]["text"], channel_topic=r["topic"], context=ctx)
                v = judge.judge([m], cats)[0]
                f.write(json.dumps({"id": r["id"], "repeat": rep, "context_kept": len(ctx),
                                    "scores": {k: round(x, 5) for k, x in v.scores.items()}}) + "\n")
    _, score, _ = _load(False)
    by_id = {r["id"]: r for r in rs}
    got: dict[str, list[float]] = {}
    for line in PROBE.open(encoding="utf-8"):
        x = json.loads(line)
        got.setdefault(x["id"], []).append(x["scores"].get(by_id[x["id"]]["category"], 0.0))
    print("| row | label | ctx (repeats removed) | repeats kept | threshold |")
    print("|---|---|---|---|---|")
    for rid, v in got.items():
        cat = by_id[rid]["category"]
        print(f"| {rid} | {by_id[rid]['label']} | {score[(rid, 'ctx')]:.2f} | {statistics.mean(v):.2f} | "
              f"{DEFAULT_THRESHOLDS[cat]} |")
    tok = sum(c["input_tokens"] or 0 for c in rec.calls)
    print(f"\n{len(rec.calls)} requests, {tok:,} input tokens, ${tok * USD_PER_M / 1e6:.4f}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("check", "blind", "ask", "report", "repeat_probe"))
    ap.add_argument("--agreed-only", action="store_true",
                    help="report only the rows the blind labeller agreed with the author on")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "blind":
        blind()
    elif a.cmd == "ask":
        ask()
    elif a.cmd == "repeat_probe":
        repeat_probe()
    else:
        report(a.agreed_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
