"""Are a few varied synthetic neighbours worth their tokens for a message judged alone? JEV-89.

JEV-61 found that ten fixed, varied, off-topic chat lines as a lone message's neighbours bought +9.0
points of spam recall over the filler alone, at about four times the tokens, and could not say through
which channel: the lines were both the message's `context` field and nine extra positions asked every
question. Padding is off by default since that run, so production's request for a quiet channel is the
message at `m1` with its window as `context`, and the constant filler at `m0`.

This asks whether two or three synthetic positions keep enough of that gain to pay for themselves, and
separates the field from the positions.

**The path.** `ModerationService.moderate`, padding off, the ten comments before the message in the
service's buffer, as in `benchmark/key_order/run.py`. The synthetic lines reach the judge as its
`padding` argument, which is exactly what `JEVMOD_PAD_BATCH` would pass: the first line takes `m0`
instead of the filler, the rest trail after the message. `SynthJudge` substitutes them for whatever the
service passes (nothing, with padding off). The request goes out in the key order the judge sends.

    decision arms, 600 spam and 300 clean, the channel's own history as `context`
    filler      production: the filler at m0, the message at m1
    s2a, s3a    the first two or three lines of set A as padding (m0 and m2, or m0, m2, m3)
    s2b, s3b    the same from set B

    mechanism arms, the first 300 spam and 100 clean, no channel history
    none        the filler alone (JEV-61's `none`)
    field10     set A's ten lines as the `context` field only
    pos10       set A's ten lines as padding only (m0 and nine trailing positions)
    both10      both, which is JEV-61's `synth_on`

    python -m benchmark.synthetic_neighbours.run plan
    python -m benchmark.synthetic_neighbours.run pilot    # paid, two per arm
    python -m benchmark.synthetic_neighbours.run ask      # paid, resumable
    python -m benchmark.synthetic_neighbours.run report
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: E402

import jevmod.core.service as service_mod  # noqa: E402
from benchmark.key_order.run import _auroc  # noqa: E402
from benchmark.real_neighbours.run import (  # noqa: E402
    SYNTHETIC,
    _holm,
    _mcnemar,
    _newcombe,
    _wilson,
    eligible,
    streams,
)
from jevmod.core.context import ConversationBuffer  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import Judge, Message  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "results" / "raw.jsonl"
USD_PER_M = 0.042
SEED = 89
WINDOW = 10
N_SPAM, N_CLEAN = 600, 300
M_SPAM, M_CLEAN = 300, 100
BUDGET_TOKENS = 40_000_000  # about $1.68; the plan is about 25M
TENANT = "bench"

SET_A = SYNTHETIC  # JEV-61's ten lines, in JEV-61's order
# Set B, written for this run before it: varied in subject and register like A, sharing no line with it,
# and about no channel.
SET_B = (
    "did anyone catch the ending yesterday",
    "my cat just knocked my coffee over",
    "ok that makes sense, thanks",
    "what are you all having for dinner",
    "finally finished my exams",
    "this song has been stuck in my head all day",
    "can someone remind me what time it is there",
    "haha no way",
    "going for a run, back in an hour",
    "welcome back, long time no see",
)

# arm -> (history from the channel?, context lines, padding lines)
ARMS: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...]]] = {
    "filler": (True, (), ()),
    "s2a": (True, (), SET_A[:2]),
    "s3a": (True, (), SET_A[:3]),
    "s2b": (True, (), SET_B[:2]),
    "s3b": (True, (), SET_B[:3]),
    "none": (False, (), ()),
    "field10": (False, SET_A, ()),
    "pos10": (False, (), SET_A),
    "both10": (False, SET_A, SET_A),
}
DECISION = ("filler", "s2a", "s3a", "s2b", "s3b")
MECHANISM = ("none", "field10", "pos10", "both10")


class Recorder:
    def __init__(self) -> None:
        self.inner = TypeSafeClient(
            api_key=get_api_key(),
            retry=RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                              http_statuses={429, 500, 502, 503, 504, 529}),
            timeout=30.0,
        )
        self.local = threading.local()

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        resp = self.inner.system_one(state=state, questions=questions)
        usage = getattr(resp, "usage", None)
        self.local.calls.append({"input_tokens": getattr(usage, "input_tokens", 0) or 0,
                                 "order": ",".join(state["messages"]),
                                 "m0": state["messages"]["m0"]["text"][:40]})
        return resp


class SynthJudge(Judge):
    """The real judge, with this arm's lines as the padding in place of what the service passes."""

    synthetic: tuple[str, ...] = ()

    def judge(self, messages, categories, custom_rules=None, padding=()):  # type: ignore[no-untyped-def]
        return super().judge(messages, categories, custom_rules, self.synthetic)


def targets() -> dict[str, list[dict[str, Any]]]:
    data = streams()
    seen: set[str] = set()
    pool: dict[str, list[dict[str, Any]]] = {"spam": [], "clean": []}
    for v, i in eligible(data):
        r = data[v][i]
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        pool["spam" if r["spam"] else "clean"].append(
            {"id": r["id"], "text": r["text"], "history": [x["text"] for x in data[v][max(0, i - WINDOW):i]]})
    rng = random.Random(SEED)
    for side in pool:
        rng.shuffle(pool[side])
    return {"spam": pool["spam"][:N_SPAM], "clean": pool["clean"][:N_CLEAN]}


def _plan() -> list[tuple[str, str, dict[str, Any]]]:
    t = targets()
    plan = []
    for side, n_m in (("spam", M_SPAM), ("clean", M_CLEAN)):
        for k, it in enumerate(t[side]):
            for arm in DECISION:
                plan.append((arm, side, it))
            if k < n_m:
                for arm in MECHANISM:
                    plan.append((arm, side, it))
    return plan


def one(rec: Recorder, arm: str, side: str, it: dict[str, Any]) -> dict[str, Any]:
    use_hist, ctx, pad = ARMS[arm]
    store = Store(":memory:")
    store.set_plan(TENANT, "unlimited")
    judge = SynthJudge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
    judge.synthetic = pad
    svc = ModerationService(store, judge=judge)
    svc.context = ConversationBuffer(window=WINDOW)
    for text in (it["history"] if use_hist else ctx):
        svc.context.add((TENANT, ""), text)
    rec.local.calls = []
    if service_mod.PAD_BATCH:
        raise RuntimeError("this run measures production with padding off")
    msg = Message(it["id"], it["text"])
    d = svc.moderate(TENANT, [msg])[0]
    calls = rec.local.calls
    return {"arm": arm, "side": side, "id": it["id"], "judged": d.judged, "reason": d.reason,
            "scores": {k: round(v, 4) for k, v in d.scores.items()},
            "input_tokens": sum(c["input_tokens"] for c in calls), "context_kept": len(msg.context),
            "orders": [c["order"] for c in calls], "m0": [c["m0"] for c in calls]}


def _done() -> tuple[set[tuple[str, str]], int]:
    done, spent = set(), 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            spent += r["input_tokens"]
            if r["judged"]:
                done.add((r["arm"], r["id"]))
    return done, spent


def ask(limit: int | None = None, workers: int = 4) -> None:
    OUT.parent.mkdir(exist_ok=True)
    done, spent = _done()
    plan = [p for p in _plan() if (p[0], p[2]["id"]) not in done]
    if limit is not None:
        per: dict[str, int] = {}
        kept = []
        for p in plan:
            if per.get(p[0], 0) < limit:
                per[p[0]] = per.get(p[0], 0) + 1
                kept.append(p)
        plan = kept
    random.Random(SEED + 1).shuffle(plan)
    rec = Recorder()
    lock = threading.Lock()
    t0 = time.time()
    state = {"spent": spent, "n": 0, "stop": False}
    service_mod.PAD_BATCH = False
    with OUT.open("a", encoding="utf-8") as f:
        def work(p: tuple[str, str, dict[str, Any]]) -> None:
            if state["stop"]:
                return
            row = one(rec, *p)
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
                state["spent"] += row["input_tokens"]
                state["n"] += 1
                if state["spent"] > BUDGET_TOKENS:
                    state["stop"] = True
                if state["n"] % 200 == 0:
                    print(f"  {state['n']}/{len(plan)}  {state['spent']:,} tok  "
                          f"${state['spent'] * USD_PER_M / 1e6:.3f}  {time.time() - t0:.0f}s", flush=True)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, plan))
    print(f"done: {state['n']} rows this run, {state['spent']:,} input tokens in the file, "
          f"${state['spent'] * USD_PER_M / 1e6:.4f}" + ("  STOPPED AT BUDGET" if state["stop"] else ""))


def rows() -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        if r["judged"]:
            out.setdefault(r["arm"], {}).setdefault(r["id"], r)
    return out


def contrast(res: dict[str, dict[str, dict[str, Any]]], first: str, second: str, side: str, cat: str,
             th: float) -> dict[str, Any] | None:
    a_, b_ = res.get(first, {}), res.get(second, {})
    ids = sorted(i for i in set(a_) & set(b_) if a_[i]["side"] == side)
    if not ids:
        return None
    x = [a_[i]["scores"][cat] >= th for i in ids]
    y = [b_[i]["scores"][cat] >= th for i in ids]
    a = sum(p and q for p, q in zip(x, y, strict=True))
    b = sum(p and not q for p, q in zip(x, y, strict=True))
    c = sum(q and not p for p, q in zip(x, y, strict=True))
    d = len(ids) - a - b - c
    delta, lo, hi = _newcombe(a, b, c, d)
    tok = sum(a_[i]["input_tokens"] for i in ids) / sum(b_[i]["input_tokens"] for i in ids)
    return {"n": len(ids), "first": (a + b) / len(ids), "second": (a + c) / len(ids), "b": b, "c": c,
            "delta": delta, "lo": lo, "hi": hi, "p": _mcnemar(b, c), "multiplier": tok,
            "mean_diff": sum(a_[i]["scores"][cat] - b_[i]["scores"][cat] for i in ids) / len(ids)}


def _row(name: str, side: str, cat: str, th: float, c: dict[str, Any], holm: float | None = None) -> str:
    return (f"| {name} | {side} | {cat} {th} | {c['n']} | {100 * c['first']:.1f}% | {100 * c['second']:.1f}% | "
            f"{100 * c['delta']:+.1f} [{100 * c['lo']:+.1f}, {100 * c['hi']:+.1f}] | {c['b']} / {c['c']} | "
            f"{c['p']:.3g}" + (f" | {holm:.3g}" if holm is not None else "")
            + f" | {c['mean_diff']:+.3f} | {c['multiplier']:.2f}x |")


def report() -> None:
    all_rows = [json.loads(line) for line in OUT.open(encoding="utf-8")]
    tokens = sum(r["input_tokens"] for r in all_rows)
    unjudged = [r for r in all_rows if not r["judged"]]
    print(f"{len(all_rows)} rows, {len(unjudged)} unjudged ({sorted({r['reason'] for r in unjudged})}), "
          f"{tokens:,} billed input tokens, ${tokens * USD_PER_M / 1e6:.3f}")
    print("key order and m0 on the wire: "
          + str({r["arm"]: (r["orders"][0], r["m0"][0]) for r in all_rows if r["orders"]}) + "\n")
    res = rows()
    print("## Per arm (spam at 0.85, Wilson 95%)\n")
    print("| arm | n spam | spam recall | n clean | clean over 0.85 | clean over 0.50 | tokens per message |")
    print("|---|---|---|---|---|---|---|")
    for arm in DECISION + MECHANISM:
        rs = list(res.get(arm, {}).values())
        pos = [r for r in rs if r["side"] == "spam"]
        neg = [r for r in rs if r["side"] == "clean"]
        if not pos or not neg:
            continue
        k = sum(r["scores"]["spam"] >= 0.85 for r in pos)
        lo, hi = _wilson(k, len(pos))
        print(f"| `{arm}` | {len(pos)} | {100 * k / len(pos):.1f}% [{100 * lo:.1f}, {100 * hi:.1f}] | {len(neg)} | "
              f"{sum(r['scores']['spam'] >= 0.85 for r in neg)} | {sum(r['scores']['spam'] >= 0.5 for r in neg)} | "
              f"{sum(r['input_tokens'] for r in rs) / len(rs):,.0f} |")

    head = ("| first vs second | side | category at line | n | first | second | difference [Newcombe 95%] | "
            "b / c | McNemar p{} | mean score difference | token multiplier |")
    print("\n## Decision contrasts against `filler` (Holm over the four, spam side)\n")
    print(head.format(" | Holm"))
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    found = {a: contrast(res, a, "filler", "spam", "spam", 0.85) for a in DECISION[1:]}
    found = {a: c for a, c in found.items() if c}
    adj = _holm({a: c["p"] for a, c in found.items()})
    for a, c in found.items():
        print(_row(f"`{a}` vs `filler`", "spam", "spam", 0.85, c, adj[a]))
    print("\n## Guards: messages without the label\n")
    print(head.format(""))
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    fired: dict[str, list[str]] = {a: [] for a in DECISION[1:]}
    for a in DECISION[1:]:
        for cat, th in (("spam", 0.85), ("spam", 0.5), ("scam", 0.75), ("scam", 0.5),
                        ("harassment", 0.75), ("harassment", 0.5)):
            c = contrast(res, a, "filler", "clean", cat, th)
            if not c:
                continue
            print(_row(f"`{a}` vs `filler`", "clean", cat, th, c))
            if c["p"] < 0.05 and c["delta"] > 0:
                fired[a].append(f"{cat} over {th} rises {100 * c['delta']:+.1f}, p {c['p']:.3g}")

    print("\n## Mechanism (spam side, 300; clean side, 100)\n")
    print(head.format(""))
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for f_, s_ in (("both10", "none"), ("field10", "none"), ("pos10", "none"), ("both10", "pos10"),
                   ("both10", "field10")):
        for side in ("spam", "clean"):
            c = contrast(res, f_, s_, side, "spam", 0.85 if side == "spam" else 0.5)
            if c:
                print(_row(f"`{f_}` vs `{s_}`", side, "spam", 0.85 if side == "spam" else 0.5, c))

    # Not pre-registered; added after the run. The question JEV-88's report asks of the key order: does
    # the arm separate spam from clean better, or move every score up so the line catches more?
    print("\n## Separation or shift (added after the run, descriptive)\n")
    print("| arm | against | AUROC arm | AUROC against | arm at 0.85 | `against` reaches that recall at | "
          "clean over the line, arm / against there |")
    print("|---|---|---|---|---|---|---|")
    for base, arms in (("filler", DECISION[1:]), ("none", MECHANISM[1:])):
        b_ = res.get(base, {})
        for a in arms:
            x = res.get(a, {})
            ids = [i for i in x if i in b_]
            pos = [i for i in ids if x[i]["side"] == "spam"]
            neg = [i for i in ids if x[i]["side"] == "clean"]
            if not pos or not neg:
                continue
            ra = sum(x[i]["scores"]["spam"] >= 0.85 for i in pos)
            t = 0.85
            while t > 0.3 and sum(b_[i]["scores"]["spam"] >= t for i in pos) < ra:
                t = round(t - 0.01, 2)
            print(f"| `{a}` | `{base}` | {_auroc(x, pos, neg, 'spam'):.4f} | {_auroc(b_, pos, neg, 'spam'):.4f} | "
                  f"{ra}/{len(pos)} | {t} ({sum(b_[i]['scores']['spam'] >= t for i in pos)}) | "
                  f"{sum(x[i]['scores']['spam'] >= 0.85 for i in neg)} / "
                  f"{sum(b_[i]['scores']['spam'] >= t for i in neg)} |")

    print("\n## The criterion\n")
    passing = {}
    for a, c in found.items():
        ok = adj[a] < 0.05 and c["lo"] >= 0.05 and c["multiplier"] <= 1.75 and not fired[a]
        passing[a] = ok
        print(f"- `{a}`: {100 * c['delta']:+.1f} [{100 * c['lo']:+.1f}, {100 * c['hi']:+.1f}], Holm p {adj[a]:.3g}, "
              f"{c['multiplier']:.2f}x, guards {fired[a] or 'none'} -> {'passes' if ok else 'fails'}")
    ship = [k for k in ("2", "3") if passing.get(f"s{k}a") and passing.get(f"s{k}b")]
    print(f"- **{'ship ' + ship[0] + ' synthetic lines' if ship else 'nothing ships'}**")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "report"
    if cmd == "plan":
        p = _plan()
        print({a: sum(1 for x in p if x[0] == a) for a in ARMS})
        return 0
    if cmd == "pilot":
        ask(limit=2)
        return 0
    if cmd == "ask":
        ask()
        return 0
    if cmd == "report":
        report()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
