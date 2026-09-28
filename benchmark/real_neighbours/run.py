"""What padding a quiet channel's message with its own history buys over the filler alone. JEV-61.

`jevmod/core/service.py` pads a batch under ten messages from one channel with that channel's recent
history: the oldest line at `m0`, the message at `m1`, up to eight more behind it, every one of them
asked every question and the answers thrown away. JEV-67 measured what that costs, 4.53 times the
request of a message judged alone, 92% to 96% of it the padding (`benchmark/context_cost/REPORT.md`).
Nothing measured what it buys. The arms that exist (`BATCH_EFFECT.md` section 9: 26.7% spam recall
with the filler alone, 29.3% with the filler and eight spam messages from the same pool, 38.7% in a
real batch of ten) are none of them production's padding, and two of them have no runner.

This one runs production's path and changes one thing at a time.

**The path.** Every request goes through a fresh `ModerationService.moderate` on an in-memory `Store`
with the default policy, as `benchmark/context_cost/run.py` does. The service reads the window from
its own `ConversationBuffer`, attaches it to the message through `assemble`, pads from it when
`PAD_BATCH` is on, and `Judge` builds and sends the request. What an arm varies is what sits in the
buffer, and whether padding is on. The judged message is always the same.

**The streams.** The UCI YouTube comment sets in `data/youtube_spam/`, each video sorted by date and
treated as one channel. Four of the five: `Youtube04-Eminem` has 245 of its 448 rows undated, so its
order is not a stream and its history would be invented. A message is eligible when the pre-filter
lets it through and its video has at least ten spam and ten clean comments before it, so every
history arm below can be filled from the same channel's own past.

**The arms.** `WINDOW` history lines are loaded into the buffer before the message is judged.

    decision arms, 600 spam and 600 clean messages
    natural_on   the ten comments posted just before it, padding on: production on this channel
    natural_off  the same, padding off: the filler at m0, the message at m1, the window as context
    clean_on     the ten clean comments posted most recently before it, padding on: production on
                 a quiet channel whose history is ordinary conversation, which is most of them
    clean_off    the same, padding off

    mechanism arms, the first 300 of each
    none         an empty buffer: the filler at m0 and the message, nothing else (the 26.7% arm)
    synth_on     ten fixed, varied, harmless chat lines as the history, padding on. Neighbours that
                 are different from each other but are not this channel
    spam_on      the ten spam comments posted most recently before it, padding on. What a raid, or
                 a channel already full of the same kind of message, looks like
    clean_pos    `clean_on` with the message moved from m1 to a seeded index between 1 and 9, the
                 neighbours shifted to make room. The model sees the same ten lines in another order

`clean_pos` changes the request after the service builds it and before it is sent, and maps the
answers back, so the service reads the message's own answers. Nothing else is touched.

    python -m benchmark.real_neighbours.run targets     # free: the targets and the eligible counts
    python -m benchmark.real_neighbours.run pilot       # paid, a few rows per arm, prints the cost
    python -m benchmark.real_neighbours.run ask         # paid, resumable, stops at the budget
    python -m benchmark.real_neighbours.run report      # free, every table in REPORT.md

Rows hold ids, labels, scores and billed tokens, never text; the text stays in the git-ignored
`benchmark/data/`.
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from math import comb, sqrt
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: E402

import jevmod.core.service as service_mod  # noqa: E402
from jevmod.core.context import ConversationBuffer  # noqa: E402
from jevmod.core.policy import DEFAULT_THRESHOLDS  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import LEAD_FILLER, Judge, Message, normalize, prefilter  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
STREAMS = HERE.parent / "data" / "youtube_spam"
OUT = HERE / "results" / "raw.jsonl"
USD_PER_M = 0.042  # list price per million input tokens, the figure every other benchmark here uses
SEED = 61
WINDOW = 10  # what the service's buffer holds per channel (`core/context.py`)
N_DECISION = 600
N_MECHANISM = 300
EXCLUDED = {"Youtube04-Eminem"}  # 245 of 448 rows undated: no order to call history
BUDGET_TOKENS = 70_000_000  # stop past this many billed input tokens, about $2.94
TENANT = "bench"
DECISION_ARMS = ("natural_on", "natural_off", "clean_on", "clean_off")
MECHANISM_ARMS = ("none", "synth_on", "spam_on", "clean_pos")
ARMS = DECISION_ARMS + MECHANISM_ARMS

# Ten harmless chat lines, different from each other in subject and register, and deliberately not
# about any video: a filler production could use would have to fit every channel. `LEAD_FILLER` is
# not among them, so the `none` arm's m0 is not also one of these.
SYNTHETIC = (
    "anyone else just get home from work?",
    "that was a good match last night",
    "lol same here",
    "what time does the stream start tomorrow",
    "thanks for the help earlier, it worked",
    "i think it's going to rain all weekend",
    "has anyone tried the new update yet",
    "good morning from spain",
    "brb grabbing some food",
    "nice, congrats on finishing it",
)


def streams() -> dict[str, list[dict[str, Any]]]:
    """Each included video's comments in the order they were posted."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(STREAMS.glob("Youtube*.csv")):
        if f.stem in EXCLUDED:
            continue
        with f.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["CONTENT"].strip()]
        if any(not r["DATE"] for r in rows):
            raise SystemExit(f"{f.stem} has undated rows; its order would be invented")
        rows.sort(key=lambda r: r["DATE"])
        out[f.stem] = [{"id": f"{f.stem}:{r['COMMENT_ID']}", "text": r["CONTENT"], "spam": r["CLASS"] == "1"}
                       for r in rows]
    return out


def eligible(data: dict[str, list[dict[str, Any]]]) -> list[tuple[str, int]]:
    """(video, index) of every message a history arm can be filled for from its own channel."""
    out = []
    for v, rows in data.items():
        n_spam = n_clean = 0
        for i, r in enumerate(rows):
            if n_spam >= WINDOW and n_clean >= WINDOW and not prefilter(Message("x", r["text"])):
                out.append((v, i))
            n_spam += r["spam"]
            n_clean += not r["spam"]
    return out


def targets(data: dict[str, list[dict[str, Any]]]) -> dict[str, list[tuple[str, int]]]:
    """The judged messages, drawn once from `SEED`: 600 of each side, the first 300 of each being the
    mechanism subset. A comment id that appears twice in a video is drawn at most once."""
    rng = random.Random(SEED)
    out: dict[str, list[tuple[str, int]]] = {}
    for side in ("spam", "clean"):
        pool = [(v, i) for v, i in eligible(data) if data[v][i]["spam"] == (side == "spam")]
        rng.shuffle(pool)
        seen: set[str] = set()
        picked = []
        for v, i in pool:
            if data[v][i]["id"] not in seen:
                seen.add(data[v][i]["id"])
                picked.append((v, i))
        out[side] = picked[:N_DECISION]
        if len(out[side]) < N_DECISION:
            raise SystemExit(f"only {len(out[side])} eligible {side} messages")
    return out


def history(arm: str, rows: list[dict[str, Any]], i: int) -> list[str]:
    """What sits in the channel's buffer when message `i` arrives, oldest first."""
    before = rows[:i]
    if arm.startswith("natural"):
        return [r["text"] for r in before[-WINDOW:]]
    if arm.startswith("clean"):
        return [r["text"] for r in before if not r["spam"]][-WINDOW:]
    if arm == "spam_on":
        return [r["text"] for r in before if r["spam"]][-WINDOW:]
    if arm == "synth_on":
        return list(SYNTHETIC)
    if arm == "none":
        return []
    raise ValueError(arm)


def moved_index(target_id: str) -> int:
    """Where `clean_pos` moves the message: seeded by its id, so a resumed run moves it to the same place."""
    return random.Random(f"{SEED}:{target_id}").randint(1, 9)


class Recorder:
    """The real client, with each call's billed tokens written down. `Judge` only ever calls
    `system_one`, so that is all this forwards. When `move_to` is set for the calling thread, the
    judged message at m1 is moved to that index before sending, and the answers mapped back."""

    def __init__(self) -> None:
        self.inner = TypeSafeClient(
            api_key=get_api_key(),
            retry=RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                              http_statuses={429, 500, 502, 503, 504, 529}),
            timeout=30.0,
        )
        self.local = threading.local()

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        calls = self.local.calls
        move_to = getattr(self.local, "move_to", None)
        msgs = state["messages"]
        order = list(range(len(msgs)))  # order[new_index] = old_index
        if move_to is not None:
            # A history line identical to the message is dropped by the service, which leaves fewer
            # than ten positions; the move is then capped at the last one, and the row says where.
            move_to = min(move_to, len(msgs) - 1)
            self.local.moved_to = move_to
            order.remove(1)
            order.insert(move_to, 1)
            state = {**state, "messages": {f"m{new}": msgs[f"m{old}"] for new, old in enumerate(order)}}
        resp = self.inner.system_one(state=state, questions=questions)
        answers = resp.answers
        if move_to is not None:
            back: dict[str, Any] = {}
            for key, val in answers.items():
                head, _, pos = key.rpartition("_")
                back[f"{head}_{order[int(pos)]}"] = val
            answers = back
        usage = getattr(resp, "usage", None)
        calls.append({"input_tokens": getattr(usage, "input_tokens", 0) or 0, "positions": len(msgs),
                      "m0_filler": msgs["m0"]["text"] == LEAD_FILLER})
        return SimpleNamespace(answers=answers, usage=usage)


_URL = re.compile(r"https?://\S+|www\.\S+|\b[\w-]+\.(?:com|net|org|ru|ly|tk|info)\b", re.I)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def one(rec: Recorder, data: dict[str, list[dict[str, Any]]], arm: str, side: str, v: str, i: int) -> dict[str, Any]:
    rows = data[v]
    target = rows[i]
    hist = history(arm, rows, i)
    store = Store(":memory:")
    store.set_plan(TENANT, "unlimited")
    judge = Judge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
    svc = ModerationService(store, judge=judge)
    svc.context = ConversationBuffer(window=WINDOW)
    for text in hist:
        svc.context.add((TENANT, ""), text)
    msg = Message(target["id"], target["text"])
    rec.local.calls = []
    rec.local.move_to = moved_index(target["id"]) if arm == "clean_pos" else None
    rec.local.moved_to = None
    pad = not arm.endswith("_off")
    # `PAD_BATCH` is read by `_judge_batch` at call time from the module, and the arms run on
    # several threads, so it is set once per run of one padding value (see `ask`), never flipped
    # here. This checks the run is in the state the arm needs.
    if pad != service_mod.PAD_BATCH:
        raise RuntimeError(f"{arm} needs PAD_BATCH={pad}")
    d = svc.moderate(TENANT, [msg])[0]
    calls = rec.local.calls
    # What was in the history, as the service would have sent it: exact copies of the message are
    # dropped from the window and from the padding by the service and the judge, so they are counted
    # here and not credited as repetition the model saw.
    norm_t = normalize(target["text"]).lower()
    sent = [h for h in hist if normalize(h).lower() != norm_t and h != target["text"]]
    labels = [r["spam"] for r in rows[:i]]
    return {
        "arm": arm, "side": side, "id": target["id"], "video": v, "index": i,
        "judged": d.judged, "reason": d.reason,
        "scores": {k: round(val, 4) for k, val in d.scores.items()},
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "positions": [c["positions"] for c in calls],
        "context_kept": len(msg.context),
        "moved_to": rec.local.moved_to,
        "m0_filler": [c["m0_filler"] for c in calls],
        "history_n": len(hist),
        "history_exact_copies": len(hist) - len(sent),
        # For the natural arm: how many of the ten were spam. Labels come from the dataset.
        "history_spam": sum(labels[-WINDOW:]) if arm.startswith("natural") else None,
        "max_jaccard": round(max((_jaccard(target["text"], h) for h in sent), default=0.0), 4),
        "shares_link": bool(_URL.search(target["text"])) and any(
            set(m.lower() for m in _URL.findall(target["text"])) & set(m.lower() for m in _URL.findall(h))
            for h in sent),
    }


def _plan(data: dict[str, list[dict[str, Any]]]) -> list[tuple[str, str, str, int]]:
    t = targets(data)
    plan = []
    for side in ("spam", "clean"):
        for n, (v, i) in enumerate(t[side]):
            for arm in DECISION_ARMS:
                plan.append((arm, side, v, i))
            if n < N_MECHANISM:
                for arm in MECHANISM_ARMS:
                    plan.append((arm, side, v, i))
    return plan


def _done() -> tuple[set[tuple[str, str]], int]:
    done, spent = set(), 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            spent += r["input_tokens"]
            if r["judged"]:
                done.add((r["arm"], r["id"]))
    return done, spent


def ask(limit_per_arm: int | None = None, workers: int = 4) -> None:
    """Every (arm, message) not yet judged. Padding-on and padding-off rows run as two passes, because
    `PAD_BATCH` is a module global the service reads per call; the order within a pass is shuffled
    with a fixed seed so time of day does not load one arm."""
    data = streams()
    OUT.parent.mkdir(exist_ok=True)
    done, spent = _done()
    plan = [p for p in _plan(data) if (p[0], data[p[2]][p[3]]["id"]) not in done]
    if limit_per_arm is not None:
        per: dict[str, int] = {}
        kept = []
        for p in plan:
            if per.get(p[0], 0) < limit_per_arm:
                per[p[0]] = per.get(p[0], 0) + 1
                kept.append(p)
        plan = kept
    random.Random(SEED + 1).shuffle(plan)
    rec = Recorder()
    lock = threading.Lock()
    t0 = time.time()
    state = {"spent": spent, "n": 0, "stop": False}
    with OUT.open("a", encoding="utf-8") as f:
        for pad in (True, False):
            service_mod.PAD_BATCH = pad
            todo = [p for p in plan if (not p[0].endswith("_off")) == pad]

            def work(p: tuple[str, str, str, int]) -> None:
                if state["stop"]:
                    return
                row = one(rec, data, *p)
                with lock:
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    state["spent"] += row["input_tokens"]
                    state["n"] += 1
                    if state["spent"] > BUDGET_TOKENS:
                        state["stop"] = True
                    if state["n"] % 50 == 0:
                        print(f"  {state['n']}/{len(plan)}  {state['spent']:,} tok  "
                              f"${state['spent'] * USD_PER_M / 1e6:.3f}  {time.time() - t0:.0f}s", flush=True)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, todo))
    service_mod.PAD_BATCH = True
    print(f"done: {state['n']} rows this run, {state['spent']:,} input tokens in the file, "
          f"${state['spent'] * USD_PER_M / 1e6:.4f}" + ("  STOPPED AT BUDGET" if state["stop"] else ""))


# --- statistics ---------------------------------------------------------------------------------

def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def _mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar: a binomial test on the discordant pairs at p = 0.5."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, j) for j in range(k + 1)) / 2**n)


def _newcombe(a: int, b: int, c: int, d: int, z: float = 1.96) -> tuple[float, float, float]:
    """Difference of two paired proportions, p1 - p2, with Newcombe's (1998) method 10 interval.
    a: both positive, b: first only, c: second only, d: neither."""
    n = a + b + c + d
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = _wilson(a + b, n, z)
    l2, u2 = _wilson(a + c, n, z)
    num = a * d - b * c
    if num > 0:
        num = max(num - n / 2, 0)
    den = sqrt((a + b) * (c + d) * (a + c) * (b + d))
    phi = num / den if den else 0.0
    delta = p1 - p2
    lo = delta - sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = delta + sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return delta, lo, hi


def _holm(ps: dict[str, float]) -> dict[str, float]:
    out, prev = {}, 0.0
    ranked = sorted(ps.items(), key=lambda kv: kv[1])
    for rank, (name, p) in enumerate(ranked):
        prev = max(prev, min(1.0, p * (len(ranked) - rank)))
        out[name] = prev
    return out


def rows() -> dict[str, dict[str, dict[str, Any]]]:
    """arm -> id -> row, judged rows only, the first judged row of each (arm, id)."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        if r["judged"]:
            out.setdefault(r["arm"], {}).setdefault(r["id"], r)
    return out


def contrast(res: dict[str, dict[str, dict[str, Any]]], first: str, second: str, side: str, cat: str,
             th: float) -> dict[str, Any] | None:
    ids = sorted(set(res.get(first, {})) & set(res.get(second, {})))
    ids = [i for i in ids if res[first][i]["side"] == side]
    if not ids:
        return None
    x = [res[first][i]["scores"][cat] >= th for i in ids]
    y = [res[second][i]["scores"][cat] >= th for i in ids]
    a = sum(p and q for p, q in zip(x, y, strict=True))
    b = sum(p and not q for p, q in zip(x, y, strict=True))
    c = sum(q and not p for p, q in zip(x, y, strict=True))
    d = len(ids) - a - b - c
    delta, lo, hi = _newcombe(a, b, c, d)
    mean_diff = sum(res[first][i]["scores"][cat] - res[second][i]["scores"][cat] for i in ids) / len(ids)
    return {"n": len(ids), "first": (a + b) / len(ids), "second": (a + c) / len(ids), "b": b, "c": c,
            "delta": delta, "lo": lo, "hi": hi, "p": _mcnemar(b, c), "mean_diff": mean_diff}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}"


def report() -> None:
    res = rows()
    th_spam, th_scam = DEFAULT_THRESHOLDS["spam"], DEFAULT_THRESHOLDS["scam"]
    all_rows = [json.loads(line) for line in OUT.open(encoding="utf-8")]
    tokens = sum(r["input_tokens"] for r in all_rows)
    unjudged = [r for r in all_rows if not r["judged"]]
    print(f"{len(all_rows)} rows, {len(unjudged)} unjudged ({sorted({r['reason'] for r in unjudged})}), "
          f"{tokens:,} billed input tokens, ${tokens * USD_PER_M / 1e6:.3f}\n")

    print(f"## Per arm: spam at {th_spam}, scam at {th_scam}, Wilson 95%\n")
    print("| arm | n spam | spam recall | n clean | spam FPR | mean spam score, spam / clean | "
          "scam over line, spam / clean | tokens per judged message |")
    print("|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        rs = list(res.get(arm, {}).values())
        pos = [r for r in rs if r["side"] == "spam"]
        neg = [r for r in rs if r["side"] == "clean"]
        if not pos or not neg:
            print(f"| {arm} | not run |")
            continue
        k, m = sum(r["scores"]["spam"] >= th_spam for r in pos), sum(r["scores"]["spam"] >= th_spam for r in neg)
        lo, hi = _wilson(k, len(pos))
        flo, fhi = _wilson(m, len(neg))
        ms = sum(r["scores"]["spam"] for r in pos) / len(pos)
        mc = sum(r["scores"]["spam"] for r in neg) / len(neg)
        sk = sum(r["scores"]["scam"] >= th_scam for r in pos) / len(pos)
        sc = sum(r["scores"]["scam"] >= th_scam for r in neg) / len(neg)
        tok = sum(r["input_tokens"] for r in rs) / len(rs)
        print(f"| `{arm}` | {len(pos)} | {_pct(k / len(pos))}% [{_pct(lo)}, {_pct(hi)}] | {len(neg)} | "
              f"{_pct(m / len(neg))}% [{_pct(flo)}, {_pct(fhi)}] | {ms:.3f} / {mc:.3f} | "
              f"{_pct(sk)}% / {_pct(sc)}% | {tok:,.0f} |")

    def table(title: str, pairs: list[tuple[str, str]], holm: bool) -> None:
        print(f"\n## {title}\n")
        print("| first vs second | side | n | first | second | difference, points [Newcombe 95%] | "
              "discordant b / c | McNemar p" + (" | Holm" if holm else "") + " | mean score difference |")
        print("|---|---|---|---|---|---|---|---" + ("|---" if holm else "") + "|---|")
        found = []
        for f_, s_ in pairs:
            for side in ("spam", "clean"):
                c = contrast(res, f_, s_, side, "spam", th_spam)
                if c:
                    found.append((f_, s_, side, c))
        adj = _holm({f"{f_}|{s_}|{side}": c["p"] for f_, s_, side, c in found}) if holm else {}
        for f_, s_, side, c in found:
            print(f"| `{f_}` vs `{s_}` | {side} | {c['n']} | {_pct(c['first'])}% | {_pct(c['second'])}% | "
                  f"{100 * c['delta']:+.1f} [{100 * c['lo']:+.1f}, {100 * c['hi']:+.1f}] | {c['b']} / {c['c']} | "
                  f"{c['p']:.3g}" + (f" | {adj[f'{f_}|{s_}|{side}']:.3g}" if holm else "")
                  + f" | {c['mean_diff']:+.3f} |")

    table("Decision contrasts (pre-registered)", [("clean_on", "clean_off"), ("natural_on", "natural_off")], False)
    table("Mechanism contrasts (Holm across this table)",
          [("synth_on", "none"), ("clean_on", "none"), ("spam_on", "clean_on"), ("natural_on", "clean_on"),
           ("clean_pos", "clean_on"), ("clean_off", "none")], True)

    # The criterion, applied mechanically. Written in REPORT.md before the paid run.
    print("\n## The criterion\n")
    for f_, s_ in (("clean_on", "clean_off"), ("natural_on", "natural_off")):
        rc = contrast(res, f_, s_, "spam", "spam", th_spam)
        fc = contrast(res, f_, s_, "clean", "spam", th_spam)
        if not rc or not fc:
            continue
        if rc["p"] < 0.05 and rc["lo"] >= 0.05 and not (fc["p"] < 0.05 and fc["delta"] > 0):
            verdict = "padding stays on"
        elif rc["hi"] < 0.05:
            verdict = "padding goes off by default"
        else:
            verdict = "inconclusive: the sample grows"
        print(f"- `{f_}` vs `{s_}`: recall {100 * rc['delta']:+.1f} [{100 * rc['lo']:+.1f}, {100 * rc['hi']:+.1f}], "
              f"p {rc['p']:.3g}; FPR {100 * fc['delta']:+.1f} [{100 * fc['lo']:+.1f}, {100 * fc['hi']:+.1f}], "
              f"p {fc['p']:.3g} -> **{verdict}**")

    # What real neighbours carry: the natural arm's lift over its own padding-off pair, by how many
    # of the ten history lines were spam, and by how close the nearest neighbour was to the message.
    print("\n## Natural history: lift of padding by what the history held (spam messages)\n")
    on, off = res.get("natural_on", {}), res.get("natural_off", {})
    ids = [i for i in set(on) & set(off) if on[i]["side"] == "spam"]

    def bucket(title: str, key) -> None:  # type: ignore[no-untyped-def]
        print(f"| {title} | n | recall off | recall on | mean lift |")
        print("|---|---|---|---|---|")
        groups: dict[str, list[str]] = {}
        for i in ids:
            groups.setdefault(key(on[i]), []).append(i)
        for g in sorted(groups):
            xs = groups[g]
            r_off = sum(off[i]["scores"]["spam"] >= th_spam for i in xs) / len(xs)
            r_on = sum(on[i]["scores"]["spam"] >= th_spam for i in xs) / len(xs)
            lift = sum(on[i]["scores"]["spam"] - off[i]["scores"]["spam"] for i in xs) / len(xs)
            print(f"| {g} | {len(xs)} | {_pct(r_off)}% | {_pct(r_on)}% | {lift:+.3f} |")
        print()

    if ids:
        bucket("spam among the ten", lambda r: {0: "0-2", 1: "0-2", 2: "0-2", 3: "3-5", 4: "3-5", 5: "3-5",
                                                 6: "6-8", 7: "6-8", 8: "6-8"}.get(r["history_spam"], "9-10"))
        bucket("nearest neighbour, word overlap",
               lambda r: "a: < 0.2" if r["max_jaccard"] < 0.2 else "b: 0.2-0.5" if r["max_jaccard"] < 0.5
               else "c: >= 0.5")
        bucket("shares a link with a neighbour", lambda r: "yes" if r["shares_link"] else "no")
        copies = sum(1 for i in ids if on[i]["history_exact_copies"])
        print(f"{copies} of {len(ids)} spam messages had an exact copy of themselves in the ten, which the service "
              f"drops from the window and the padding.\n")

    moved = res.get("clean_pos", {})
    base = res.get("clean_on", {})
    pids = [i for i in set(moved) & set(base) if moved[i]["side"] == "spam"]
    if pids:
        print("## `clean_pos`: the message's own spam score by the index it was moved to (spam messages)\n")
        print("| index | n | clean_on (index 1) | clean_pos | mean difference |")
        print("|---|---|---|---|---|")
        by: dict[int, list[str]] = {}
        for i in pids:
            by.setdefault(moved[i]["moved_to"], []).append(i)
        for k in sorted(by):
            xs = by[k]
            a_ = sum(base[i]["scores"]["spam"] for i in xs) / len(xs)
            b_ = sum(moved[i]["scores"]["spam"] for i in xs) / len(xs)
            print(f"| {k} | {len(xs)} | {a_:.3f} | {b_:.3f} | {b_ - a_:+.3f} |")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "report"
    if cmd == "targets":
        data = streams()
        t = targets(data)
        el = eligible(data)
        print({v: len(rows) for v, rows in data.items()})
        print(f"eligible: {sum(data[v][i]['spam'] for v, i in el)} spam, "
              f"{sum(not data[v][i]['spam'] for v, i in el)} clean")
        for side, xs in t.items():
            print(side, len(xs), {v: sum(1 for x in xs if x[0] == v) for v in data})
        return 0
    if cmd == "pilot":
        ask(limit_per_arm=3, workers=4)
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
