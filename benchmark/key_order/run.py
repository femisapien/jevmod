"""Does the order of the keys in `state.messages` move Jev's scores? JEV-88.

`Judge._request` builds `state["messages"]` with the real messages first and adds `m0` after, so the
JSON the API receives reads `m1, m0` for a message judged alone and `m1, ..., mN, m0` for a batch. The
SDK encodes the dict in insertion order (`typesafe_sdk._core.json.serialize`, msgspec, no key sorting);
this runner checks that on every request rather than assuming it. JEV-61 found, in an arm built for
something else, that sending `m0` first raised the spam score of 22 of 29 spam messages. This measures it
on purpose, with the padding off as production now runs.

**The path.** Every request goes through a fresh `ModerationService.moderate` on an in-memory `Store`,
the default policy, `JEVMOD_PAD_BATCH` off, the history in the service's own `ConversationBuffer`, as
`benchmark/real_neighbours/run.py` does. The only thing an arm changes is the insertion order of
`state["messages"]` in the request `Judge` built, just before it is sent. Keys, texts, questions and
answers are untouched, so nothing has to be mapped back.

    current     as the judge sends it: m1, ..., mN, m0
    m0_first    by index: m0, m1, ..., mN
    sorted_lex  as `json.dumps(sort_keys=True)` would: m0, m1, m10, m11, ..., m2, ...; differs from
                `m0_first` only with ten or more positions, so it runs in the batch regime only
    repeat      `current` again, the same request a second time: the noise floor

**The sets.**

    yt    lone   the eligible messages of JEV-61's four dated YouTube streams (653 spam, 629 clean),
                 each judged alone with the ten comments before it as its `context` field, which is
                 production's request for a quiet channel with padding off
    hx    lone   harassment: every `openai_moderation` row labelled harassment and every Civil Comments
                 row at toxicity 0.7 or more, against Civil Comments at 0.1 or less and a seeded 250 of
                 the unlabelled `openai_moderation` rows; no history
    rt    lone   `tests/data/redteam.csv`, 98 rows with their topics; the only scam labels the repository
                 has, descriptive only
    ytb   batch  the four streams in posting order, in consecutive batches of 25, each with the ten comments
                 before it in the buffer
    hxb   batch  the `hx` set in a seeded order, batches of 25

    python -m benchmark.key_order.run plan      # free: set sizes and the request count per arm
    python -m benchmark.key_order.run pilot     # paid, two units per (set, arm), prints the cost
    python -m benchmark.key_order.run ask       # paid, resumable, stops at the budget
    python -m benchmark.key_order.run report    # free, every table in REPORT.md

Rows hold ids, labels, scores, billed tokens and the key order that went on the wire, never text.
"""

from __future__ import annotations

import csv
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: E402
from typesafe_sdk._core.json import serialize  # noqa: E402

import jevmod.core.service as service_mod  # noqa: E402
from benchmark.real_neighbours.run import _holm, _mcnemar, _newcombe, _wilson, eligible, streams  # noqa: E402
from jevmod.core.context import ConversationBuffer  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import Judge, Message  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
DATA = HERE.parent / "data"
REDTEAM = HERE.parents[1] / "tests" / "data" / "redteam.csv"
OUT = HERE / "results" / "raw.jsonl"
USD_PER_M = 0.042
SEED = 88
WINDOW = 10
BATCH = 25
BUDGET_TOKENS = 45_000_000  # about $1.89; the plan is about 30M
TENANT = "bench"
LONE_ARMS = ("current", "m0_first", "repeat")
BATCH_ARMS = ("current", "m0_first", "sorted_lex")
ARMS_BY_SET = {"yt": LONE_ARMS, "hx": LONE_ARMS, "rt": ("current", "m0_first"),
               "ytb": BATCH_ARMS, "hxb": BATCH_ARMS}
LINES = {"spam": (0.85, 0.50), "scam": (0.75, 0.50), "harassment": (0.75, 0.50)}


def order_keys(arm: str, keys: list[str]) -> list[str]:
    if arm in ("current", "repeat"):
        return list(keys)
    if arm == "m0_first":
        return sorted(keys, key=lambda k: int(k[1:]))
    if arm == "sorted_lex":
        return sorted(keys)
    raise ValueError(arm)


# --- the sets -------------------------------------------------------------------------------------

def _yt_items() -> list[dict[str, Any]]:
    data = streams()
    seen: set[str] = set()
    out = []
    for v, i in eligible(data):
        r = data[v][i]
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append({"id": r["id"], "text": r["text"], "labels": ["spam"] if r["spam"] else [],
                    "history": [x["text"] for x in data[v][max(0, i - WINDOW):i]], "topic": ""})
    return out


def _hx_items() -> list[dict[str, Any]]:
    out = []
    unlabelled = []
    for i, line in enumerate((DATA / "openai_moderation.jsonl").open(encoding="utf-8")):
        r = json.loads(line)
        if any(r.get(k) == 1 for k in ("H", "HR", "V")):
            out.append({"id": f"oai{i}", "text": r["prompt"], "labels": ["harassment"]})
        elif not any(r.get(k) == 1 for k in ("S", "S3", "H", "HR", "V", "V2", "SH")):
            unlabelled.append({"id": f"oai{i}", "text": r["prompt"], "labels": []})
    for i, line in enumerate((DATA / "civil_comments.jsonl").open(encoding="utf-8")):
        r = json.loads(line)
        if r["toxicity"] >= 0.7:
            out.append({"id": f"cc{i}", "text": r["text"], "labels": ["harassment"]})
        elif r["toxicity"] <= 0.1:
            out.append({"id": f"cc{i}", "text": r["text"], "labels": []})
    random.Random(SEED).shuffle(unlabelled)
    out += unlabelled[:250]
    for r in out:
        r["history"], r["topic"] = [], ""
    return out


def _rt_items() -> list[dict[str, Any]]:
    with REDTEAM.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [{"id": f"rt:{r['id']}", "text": r["text"], "topic": r["topic"], "history": [],
             "labels": [x for x in r["expected"].split("|") if x and x != "none"]} for r in rows]


def _ytb_units() -> list[dict[str, Any]]:
    data = streams()
    units = []
    for v, rows in data.items():
        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            units.append({"unit": f"{v}:{start}", "history": [x["text"] for x in rows[max(0, start - WINDOW):start]],
                          "items": [{"id": r["id"], "text": r["text"], "labels": ["spam"] if r["spam"] else []}
                                    for r in chunk], "topic": ""})
    return units


def _hxb_units() -> list[dict[str, Any]]:
    items = _hx_items()
    random.Random(SEED + 1).shuffle(items)
    return [{"unit": f"hxb:{k}", "history": [], "topic": "",
             "items": [{"id": r["id"], "text": r["text"], "labels": r["labels"]} for r in items[k:k + BATCH]]}
            for k in range(0, len(items), BATCH)]


def units() -> dict[str, list[dict[str, Any]]]:
    """set -> units; a lone unit holds one item."""
    lone = {"yt": _yt_items(), "hx": _hx_items(), "rt": _rt_items()}
    out: dict[str, list[dict[str, Any]]] = {
        s: [{"unit": it["id"], "history": it["history"], "topic": it["topic"], "items": [it]} for it in xs]
        for s, xs in lone.items()}
    out["ytb"] = _ytb_units()
    out["hxb"] = _hxb_units()
    return out


# --- the client -----------------------------------------------------------------------------------

class Recorder:
    """The real client. Reorders `state.messages` for the calling thread's arm, checks the order that
    goes on the wire, and writes down each call's billed tokens."""

    def __init__(self) -> None:
        self.inner = TypeSafeClient(
            api_key=get_api_key(),
            retry=RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                              http_statuses={429, 500, 502, 503, 504, 529}),
            timeout=30.0,
        )
        self.local = threading.local()

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        arm = self.local.arm
        msgs = state["messages"]
        built = list(msgs)
        # The claim this whole run rests on: production sends m0 last. If the judge ever changes that,
        # `current` stops meaning production and the run must stop rather than measure something else.
        if self.local.expect_current and built[-1] != "m0" and len(built) > 1:
            raise RuntimeError(f"judge no longer sends m0 last: {built}")
        keys = order_keys(arm, built)
        state = {**state, "messages": {k: msgs[k] for k in keys}}
        wire = json.loads(serialize(state))  # what the SDK encodes, parsed back in its order
        sent = list(wire["messages"])
        if sent != keys:
            raise RuntimeError(f"the SDK reordered the keys: {keys} -> {sent}")
        resp = self.inner.system_one(state=state, questions=questions)
        usage = getattr(resp, "usage", None)
        self.local.calls.append({"input_tokens": getattr(usage, "input_tokens", 0) or 0, "order": ",".join(sent)})
        return SimpleNamespace(answers=resp.answers, usage=usage)


def one(rec: Recorder, set_name: str, arm: str, unit: dict[str, Any], expect_current: bool) -> list[dict[str, Any]]:
    store = Store(":memory:")
    store.set_plan(TENANT, "unlimited")
    judge = Judge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
    svc = ModerationService(store, judge=judge)
    svc.context = ConversationBuffer(window=WINDOW)
    for text in unit["history"]:
        svc.context.add((TENANT, ""), text)
    msgs = [Message(it["id"], it["text"], channel_topic=unit["topic"]) for it in unit["items"]]
    rec.local.calls = []
    rec.local.arm = arm
    rec.local.expect_current = expect_current
    if service_mod.PAD_BATCH:
        raise RuntimeError("this run measures production with padding off")
    ds = svc.moderate(TENANT, msgs)
    calls = rec.local.calls
    tokens = sum(c["input_tokens"] for c in calls)
    judged = sum(d.judged for d in ds) or 1
    out = []
    for it, d in zip(unit["items"], ds, strict=True):
        out.append({
            "set": set_name, "arm": arm, "unit": unit["unit"], "id": it["id"], "labels": it["labels"],
            "judged": d.judged, "reason": d.reason,
            "scores": {k: round(v, 4) for k, v in d.scores.items()},
            # A batch's tokens are shared out over the messages it judged; the per-row figure is for
            # the per-arm table, and `unit_tokens` is the exact bill of the request(s).
            "input_tokens": tokens / judged if d.judged else 0, "unit_tokens": tokens,
            "orders": [c["order"] for c in calls],
        })
    return out


def _plan() -> list[tuple[str, str, dict[str, Any]]]:
    plan = []
    for s, us in units().items():
        for u in us:
            for arm in ARMS_BY_SET[s]:
                plan.append((s, arm, u))
    return plan


def _done() -> tuple[set[tuple[str, str, str]], int]:
    done, spent = set(), 0
    if OUT.exists():
        seen_units: set[tuple[str, str, str]] = set()
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            key = (r["set"], r["arm"], r["unit"])
            if key not in seen_units:
                spent += r["unit_tokens"]
                seen_units.add(key)
            if r["judged"]:
                done.add(key)
    return done, spent


def ask(limit: int | None = None, workers: int = 4) -> None:
    """Every (set, arm, unit) not yet judged, all arms interleaved in one seeded order, so time of day
    and any drift in the service load every arm alike."""
    OUT.parent.mkdir(exist_ok=True)
    done, spent = _done()
    plan = [p for p in _plan() if (p[0], p[1], p[2]["unit"]) not in done]
    if limit is not None:
        per: dict[tuple[str, str], int] = {}
        kept = []
        for p in plan:
            if per.get((p[0], p[1]), 0) < limit:
                per[(p[0], p[1])] = per.get((p[0], p[1]), 0) + 1
                kept.append(p)
        plan = kept
    random.Random(SEED + 2).shuffle(plan)
    rec = Recorder()
    lock = threading.Lock()
    t0 = time.time()
    state = {"spent": spent, "n": 0, "stop": False}
    service_mod.PAD_BATCH = False
    with OUT.open("a", encoding="utf-8") as f:
        def work(p: tuple[str, str, dict[str, Any]]) -> None:
            if state["stop"]:
                return
            try:
                rows = one(rec, p[0], p[1], p[2], expect_current=p[1] in ("current", "repeat"))
            except RuntimeError as exc:
                print(f"STOP: {exc}", flush=True)
                state["stop"] = True
                return
            with lock:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
                f.flush()
                state["spent"] += rows[0]["unit_tokens"]
                state["n"] += 1
                if state["spent"] > BUDGET_TOKENS:
                    state["stop"] = True
                if state["n"] % 100 == 0:
                    print(f"  {state['n']}/{len(plan)}  {state['spent']:,} tok  "
                          f"${state['spent'] * USD_PER_M / 1e6:.3f}  {time.time() - t0:.0f}s", flush=True)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, plan))
    print(f"done: {state['n']} units this run, {state['spent']:,} input tokens in the file, "
          f"${state['spent'] * USD_PER_M / 1e6:.4f}" + ("  STOPPED" if state["stop"] else ""))


# --- the report -----------------------------------------------------------------------------------

def rows() -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """(set, arm) -> id -> the first judged row."""
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        if r["judged"]:
            out.setdefault((r["set"], r["arm"]), {}).setdefault(r["id"], r)
    return out


def paired(res: dict[tuple[str, str], dict[str, dict[str, Any]]], s: str, first: str, second: str,
           positive: bool, label: str, cat: str, th: float) -> dict[str, Any] | None:
    """`first` against `second` on the rows of set `s` that carry `label` (positive) or do not."""
    a_, b_ = res.get((s, first), {}), res.get((s, second), {})
    ids = sorted(i for i in set(a_) & set(b_) if (label in a_[i]["labels"]) == positive)
    if not ids:
        return None
    x = [a_[i]["scores"][cat] >= th for i in ids]
    y = [b_[i]["scores"][cat] >= th for i in ids]
    a = sum(p and q for p, q in zip(x, y, strict=True))
    b = sum(p and not q for p, q in zip(x, y, strict=True))
    c = sum(q and not p for p, q in zip(x, y, strict=True))
    d = len(ids) - a - b - c
    delta, lo, hi = _newcombe(a, b, c, d)
    diffs = [a_[i]["scores"][cat] - b_[i]["scores"][cat] for i in ids]
    up, down = sum(v > 0 for v in diffs), sum(v < 0 for v in diffs)
    return {"n": len(ids), "first": (a + b) / len(ids), "second": (a + c) / len(ids), "b": b, "c": c,
            "delta": delta, "lo": lo, "hi": hi, "p": _mcnemar(b, c), "mean_diff": sum(diffs) / len(ids),
            "up": up, "down": down, "p_sign": _mcnemar(up, down)}


def _auroc(arm: dict[str, dict[str, Any]], pos: list[str], neg: list[str], cat: str) -> float:
    """Mann-Whitney: the chance a positive outscores a negative, ties counted half."""
    ranked = sorted([(arm[i]["scores"][cat], 1) for i in pos] + [(arm[i]["scores"][cat], 0) for i in neg])
    rank_sum, k = 0.0, 0
    while k < len(ranked):
        j = k
        while j < len(ranked) and ranked[j][0] == ranked[k][0]:
            j += 1
        mid = (k + j + 1) / 2  # ranks are 1-based; a tie shares the mean rank of its run
        rank_sum += mid * sum(flag for _, flag in ranked[k:j])
        k = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def _fmt(c: dict[str, Any]) -> str:
    return (f"{c['n']} | {100 * c['first']:.1f}% | {100 * c['second']:.1f}% | "
            f"{100 * c['delta']:+.1f} [{100 * c['lo']:+.1f}, {100 * c['hi']:+.1f}] | {c['b']} / {c['c']} | "
            f"{c['p']:.3g} | {c['mean_diff']:+.4f} | {c['up']} / {c['down']} | {c['p_sign']:.3g}")


HEAD = ("| n | first | second | difference, points [Newcombe 95%] | flips b / c | McNemar p | "
        "mean score difference | scores up / down | sign p |")
SEP = "|---|---|---|---|---|---|---|---|---|"
LABEL_OF = {"spam": "spam", "scam": "scam", "harassment": "harassment"}
SETS_OF = {"spam": ("yt", "ytb"), "harassment": ("hx", "hxb"), "scam": ("rt",)}


def guards(res: dict[tuple[str, str], dict[str, dict[str, Any]]], first: str, second: str) -> list[str]:
    """Every pre-registered harm check for `first` against `second`; returns the ones that fired."""
    fired = []
    for s in ("yt", "ytb", "hx", "hxb"):
        if (s, first) not in res or (s, second) not in res:
            continue
        own = "spam" if s.startswith("yt") else "harassment"
        th = LINES[own][0]
        c = paired(res, s, first, second, True, own, own, th)
        if c and c["p"] < 0.05 and c["delta"] < 0:
            fired.append(f"{s}: {own} recall at {th} falls {100 * c['delta']:+.1f}, p {c['p']:.3g}")
        for cat, lines in LINES.items():
            for th in lines:
                c = paired(res, s, first, second, False, cat if cat != "scam" else own, cat, th)
                if c and c["p"] < 0.05 and c["delta"] > 0:
                    fired.append(f"{s}: {cat} over {th} on messages not labelled "
                                 f"{cat if cat != 'scam' else own} rises {100 * c['delta']:+.1f}, p {c['p']:.3g}")
    return fired


def report() -> None:
    all_rows = [json.loads(line) for line in OUT.open(encoding="utf-8")]
    billed: dict[tuple[str, str, str], int] = {}
    for r in all_rows:
        billed.setdefault((r["set"], r["arm"], r["unit"]), r["unit_tokens"])
    tokens = sum(billed.values())
    unjudged = [r for r in all_rows if not r["judged"]]
    orders = {r["arm"]: r["orders"][0] for r in all_rows if r["set"] == "yt" and r["orders"]}
    print(f"{len(all_rows)} rows over {len(billed)} requests' units, {len(unjudged)} rows unjudged "
          f"({sorted({r['reason'] for r in unjudged})}), {tokens:,} billed input tokens, "
          f"${tokens * USD_PER_M / 1e6:.3f}")
    print(f"key order on the wire, lone yt: {orders}\n")
    res = rows()

    print("## Per set and arm\n")
    print("| set | arm | n pos | recall at the line [Wilson 95%] | n neg | flagged at the line | "
          "over 0.50 | tokens per judged message |")
    print("|---|---|---|---|---|---|---|---|")
    for s, arms in ARMS_BY_SET.items():
        cat = "spam" if s.startswith("yt") else "harassment" if s.startswith("hx") else "scam"
        th = LINES[cat][0]
        for arm in arms:
            rs = list(res.get((s, arm), {}).values())
            if not rs:
                continue
            pos = [r for r in rs if cat in r["labels"]]
            neg = [r for r in rs if not r["labels"]]
            k = sum(r["scores"][cat] >= th for r in pos)
            m = sum(r["scores"][cat] >= th for r in neg)
            m5 = sum(r["scores"][cat] >= 0.5 for r in neg)
            lo, hi = _wilson(k, len(pos))
            tok = sum(r["input_tokens"] for r in rs) / len(rs)
            print(f"| {s} | `{arm}` | {len(pos)} | {cat} {100 * k / max(1, len(pos)):.1f}% [{100 * lo:.1f}, "
                  f"{100 * hi:.1f}] | {len(neg)} | {m} | {m5} | {tok:,.0f} |")

    def table(title: str, specs: list[tuple[str, str, str, bool, str, str, float]]) -> None:
        print(f"\n## {title}\n")
        print("| contrast | set | side | category at line " + HEAD)
        print("|---|---|---|---" + SEP)
        for s, f_, s_, positive, label, cat, th in specs:
            c = paired(res, s, f_, s_, positive, label, cat, th)
            if c:
                side = f"{label}" if positive else f"not {label}"
                print(f"| `{f_}` vs `{s_}` | {s} | {side} | {cat} {th} | " + _fmt(c) + " |")

    table("The primary contrast (pre-registered)", [("yt", "m0_first", "current", True, "spam", "spam", 0.85)])
    table("Recall in every set", [
        ("yt", "m0_first", "current", True, "spam", "spam", 0.85),
        ("ytb", "m0_first", "current", True, "spam", "spam", 0.85),
        ("ytb", "sorted_lex", "current", True, "spam", "spam", 0.85),
        ("ytb", "sorted_lex", "m0_first", True, "spam", "spam", 0.85),
        ("hx", "m0_first", "current", True, "harassment", "harassment", 0.75),
        ("hxb", "m0_first", "current", True, "harassment", "harassment", 0.75),
        ("hxb", "sorted_lex", "current", True, "harassment", "harassment", 0.75),
        ("rt", "m0_first", "current", True, "scam", "scam", 0.75),
        ("rt", "m0_first", "current", True, "spam", "spam", 0.85),
    ])
    fp = []
    for s, own in (("yt", "spam"), ("ytb", "spam"), ("hx", "harassment"), ("hxb", "harassment")):
        for cat, lines in LINES.items():
            for th in lines:
                fp.append((s, "m0_first", "current", False, cat if cat != "scam" else own, cat, th))
    table("False positives: messages without the label, m0_first against current", fp)
    table("The noise floor: the same request twice (`repeat` against `current`)", [
        ("yt", "repeat", "current", True, "spam", "spam", 0.85),
        ("yt", "repeat", "current", False, "spam", "spam", 0.50),
        ("hx", "repeat", "current", True, "harassment", "harassment", 0.75),
        ("hx", "repeat", "current", False, "harassment", "harassment", 0.50),
    ])

    print("\n## The criterion\n")
    c = paired(res, "yt", "m0_first", "current", True, "spam", "spam", 0.85)
    fired = guards(res, "m0_first", "current")
    if c:
        helps = c["p"] < 0.05 and c["delta"] > 0
        print(f"- primary: spam recall {100 * c['delta']:+.1f} [{100 * c['lo']:+.1f}, {100 * c['hi']:+.1f}], "
              f"{c['b']} / {c['c']}, p {c['p']:.3g} -> {'helps' if helps else 'no demonstrated gain'}")
        print(f"- guards fired: {fired or 'none'}")
        sl = paired(res, "ytb", "sorted_lex", "m0_first", True, "spam", "spam", 0.85)
        better_sorted = bool(sl and sl["p"] < 0.05 and sl["delta"] > 0)
        verdict = ("ship m0_first" if helps and not fired else "do not ship")
        if helps and not fired and better_sorted:
            verdict += " (sorted_lex beat it in batches: a follow-up)"
        print(f"- **{verdict}**")
    # Not pre-registered; added after the run to say what kind of gain the primary is. If the order
    # separated spam from clean better, the area under the ROC curve would rise; if it moved every score
    # up, the area stays and the same recall is reached on `current` with a lower line.
    print("\n## Separation or shift (added after the run, descriptive)\n")
    print("| set | category | AUROC current | AUROC m0_first | m0_first at the line: recall, over the line "
          "without the label | `current` reaches that recall at | there: recall, over the line without the label |")
    print("|---|---|---|---|---|---|---|")
    for s, cat in (("yt", "spam"), ("ytb", "spam"), ("hx", "harassment"), ("hxb", "harassment")):
        a_, b_ = res.get((s, "m0_first"), {}), res.get((s, "current"), {})
        ids = [i for i in a_ if i in b_]
        if not ids:
            continue
        pos = [i for i in ids if cat in a_[i]["labels"]]
        neg = [i for i in ids if cat not in a_[i]["labels"]]
        th = LINES[cat][0]
        ra = sum(a_[i]["scores"][cat] >= th for i in pos)
        fa = sum(a_[i]["scores"][cat] >= th for i in neg)
        t = th
        while t > 0.3 and sum(b_[i]["scores"][cat] >= t for i in pos) < ra:
            t = round(t - 0.01, 2)
        rb = sum(b_[i]["scores"][cat] >= t for i in pos)
        fb = sum(b_[i]["scores"][cat] >= t for i in neg)
        print(f"| {s} | {cat} | {_auroc(b_, pos, neg, cat):.4f} | {_auroc(a_, pos, neg, cat):.4f} | "
              f"{ra}/{len(pos)}, {fa}/{len(neg)} at {th} | {t} | {rb}/{len(pos)}, {fb}/{len(neg)} |")

    fam = {}
    for s, label in (("yt", "spam"), ("ytb", "spam"), ("hx", "harassment"), ("hxb", "harassment")):
        c2 = paired(res, s, "m0_first", "current", True, label, label, LINES[label][0])
        if c2:
            fam[f"{s} {label}"] = c2["p_sign"]
    if fam:
        print("\nSign tests on the positives' scores, Holm over the four sets: "
              + ", ".join(f"{k} {v:.2g}" for k, v in _holm(fam).items()))


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "report"
    if cmd == "plan":
        us = units()
        for s, xs in us.items():
            items = [it for u in xs for it in u["items"]]
            pos = {lab: sum(lab in it["labels"] for it in items) for lab in ("spam", "scam", "harassment")}
            print(f"{s}: {len(xs)} units, {len(items)} messages, labels {pos}, "
                  f"{len(xs) * len(ARMS_BY_SET[s])} requests over {ARMS_BY_SET[s]}")
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
