"""What the conversation window costs per judged message, by window, topic and batch size.

JEV-67. `benchmark/LOAD.md` priced the window once: batches of 25, a window of ten, on
`data/items.jsonl`, whose rows are prompts and comments rather than chat. Pricing a plan needs the
curve, not the point: the window at 0, 5, 10 and 20 messages, with and without a channel topic, at
batch sizes 1, 10, 25 and 50, because the hosted service's batch size is decided by how busy a server
is and a quiet server's batch is one message padded to ten.

**The path is production's, not a copy of it.** Every request goes through a fresh
`ModerationService.moderate` on an in-memory `Store`: the service reads the window from its own
`ConversationBuffer`, trims it with `assemble`, attaches it to each message, pads a batch under ten
from the same window, and `Judge` builds and sends the request. The only thing added is a wrapper
around the real TypeSafe client that records the tokens the API reports and the wall time of each
call. Nothing is estimated from characters.

**The stream** is the UCI YouTube comment sets in `data/youtube_spam/`, each video sorted by date and
treated as one channel. It is the shortest real text in the benchmark (median about 50 characters),
which is the closest the repository has to chat. It is not Discord and it is not threaded; the
report says what that changes.

**The arms are paired.** For each batch size, positions in the streams are drawn once from a fixed
seed, and every window and topic arm judges exactly the same messages at each position, in a
shuffled order so that time of day does not load one arm. A multiplier is then a ratio on identical
judged text, not two samples that happen to have similar lengths.

    python -m benchmark.context_cost.run ask        # paid, resumable, prints the running cost
    python -m benchmark.context_cost.run report     # free, every table in REPORT.md
"""

from __future__ import annotations

import csv
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: E402

import jevmod.core.service as service_mod  # noqa: E402
from jevmod.core.context import ConversationBuffer  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import Judge, Message  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
STREAMS = HERE.parent / "data" / "youtube_spam"
OUT = HERE / "results" / "raw.jsonl"
USD_PER_M = 0.042  # list price per million input tokens, the figure every other benchmark here uses
SEED = 20260927
WINDOWS = (0, 5, 10, 20)
TOPICS = (False, True)
# Requests per batch size. Tokens barely vary between positions of the same shape, so the sample is
# sized for latency and for the spread of message length, and kept small because it is paid.
REQUESTS = {1: 30, 10: 10, 25: 6, 50: 6}
# A channel topic of the length a Discord channel usually has. Without one, `Judge` sends
# "general chat" on every position, so "no topic" is not zero tokens and the arm measures the
# difference a real topic makes, which is the question a server owner can act on.
TOPIC = ("Comments under the official music video. Talk about the song and the artist; "
         "self-promotion and links to your own channel are not allowed.")
TENANT = "bench"
BUDGET_TOKENS = 12_000_000  # abort if the run passes this many input tokens, about $0.50


def streams() -> dict[str, list[dict[str, str]]]:
    """Each video's comments in the order they were posted. Rows with no date are kept in file order
    at the end rather than dropped, because they are still comments that were said."""
    out: dict[str, list[dict[str, str]]] = {}
    for f in sorted(STREAMS.glob("Youtube*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["CONTENT"].strip()]
        rows.sort(key=lambda r: r["DATE"] or "9999")
        out[f.stem] = [{"id": f"{f.stem}:{r['COMMENT_ID']}", "text": r["CONTENT"]} for r in rows]
    return out


def positions(data: dict[str, list[dict[str, str]]]) -> list[tuple[int, str, int]]:
    """(batch, video, start) for every request, drawn once. `start` leaves room for the largest
    window before it, so every window arm reads real history rather than the start of the file."""
    rng = random.Random(SEED)
    vids = sorted(data)
    out = []
    for batch, n in REQUESTS.items():
        for _ in range(n):
            v = rng.choice(vids)
            out.append((batch, v, rng.randrange(max(WINDOWS), len(data[v]) - batch)))
    return out


def arms(batch: int) -> list[tuple[int, bool, bool]]:
    """(window, topic, padding). Batch one also runs with padding off at every non-empty window,
    which separates the window's two costs: the `context` field on the judged message, and the
    padding positions that are asked every question and thrown away."""
    out = [(w, t, True) for w in WINDOWS for t in TOPICS]
    if batch == 1:
        out += [(w, False, False) for w in WINDOWS if w]
    return out


class Recorder:
    """The real client, with each call's reported usage and wall time written down. `Judge` only
    ever calls `system_one`, so that is all this has to forward."""

    def __init__(self) -> None:
        self.inner = TypeSafeClient(
            api_key=get_api_key(),
            retry=RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                              http_statuses={429, 500, 502, 503, 504, 529}),
            timeout=30.0,
        )
        self.calls: list[dict[str, Any]] = []
        # Calls that raised. `ModerationService` swallows the exception and fails the batch open,
        # so without this a rejected request and a timeout look the same in the results.
        self.errors: list[dict[str, Any]] = []

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        t = time.perf_counter()
        msgs = state["messages"]
        try:
            resp = self.inner.system_one(state=state, questions=questions)
        except Exception as e:
            body = getattr(e, "body", None)
            self.errors.append({
                "ms": (time.perf_counter() - t) * 1000,
                "error": type(e).__name__,
                "status": getattr(e, "status", None),
                "body": json.dumps(body, default=str)[:300] if body is not None else str(e)[:300],
                "positions": len(msgs),
                "state_chars": len(json.dumps(state, ensure_ascii=False)),
            })
            raise
        usage = getattr(resp, "usage", None)
        self.calls.append({
            "ms": (time.perf_counter() - t) * 1000,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "positions": len(msgs),
            "questions": len(questions),
            "context_entries": sum(len(m.get("context", {})) for m in msgs.values()),
            "state_chars": len(json.dumps(state, ensure_ascii=False)),
        })
        return resp


def one(rec: Recorder, data: dict[str, list[dict[str, str]]], batch: int, video: str, start: int,
        window: int, topic: bool, pad: bool) -> dict[str, Any]:
    stream = data[video]
    store = Store(":memory:")
    store.set_plan(TENANT, "unlimited")
    judge = Judge(client=rec, cache_ttl_s=0)  # type: ignore[arg-type]
    svc = ModerationService(store, judge=judge)
    # The buffer the service would have after `window` messages in this channel. `now` is left to
    # the clock: the history is added a moment before it is read, well inside the age bound.
    svc.context = ConversationBuffer(window=window)
    for r in stream[start - window : start]:
        svc.context.add((TENANT, ""), r["text"])
    msgs = [Message(r["id"], r["text"], channel_topic=TOPIC if topic else "")
            for r in stream[start : start + batch]]
    before, before_err = len(rec.calls), len(rec.errors)
    service_mod.PAD_BATCH = pad
    try:
        t = time.perf_counter()
        decisions = svc.moderate(TENANT, msgs)
        total_ms = (time.perf_counter() - t) * 1000
    finally:
        service_mod.PAD_BATCH = True
    calls = rec.calls[before:]
    return {
        "batch": batch, "video": video, "start": start, "window": window, "topic": topic, "pad": pad,
        "ids": [m.id for m in msgs],
        "judged": sum(1 for d in decisions if d.judged),
        "skipped": sorted({d.reason for d in decisions if not d.judged}),
        "context_kept": [len(m.context) for m in msgs],
        "input_tokens": sum(c["input_tokens"] or 0 for c in calls),
        "output_tokens": sum(c["output_tokens"] or 0 for c in calls),
        "calls": calls,
        "errors": rec.errors[before_err:],
        "moderate_ms": total_ms,
    }


def ask() -> None:
    data = streams()
    OUT.parent.mkdir(exist_ok=True)
    done = set()
    spent = 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            done.add((r["batch"], r["video"], r["start"], r["window"], r["topic"], r["pad"]))
            spent += r["input_tokens"]
    rng = random.Random(SEED + 1)
    rec = Recorder()
    todo = positions(data)
    with OUT.open("a", encoding="utf-8") as f:
        for k, (batch, video, start) in enumerate(todo, 1):
            order = arms(batch)
            rng.shuffle(order)  # drawn even when skipped, so a resumed run keeps the same order
            for window, topic, pad in order:
                if (batch, video, start, window, topic, pad) in done:
                    continue
                row = one(rec, data, batch, video, start, window, topic, pad)
                f.write(json.dumps(row) + "\n")
                f.flush()
                spent += row["input_tokens"]
                if spent > BUDGET_TOKENS:
                    print(f"\nstopped: {spent:,} input tokens is past the budget")
                    return
            print(f"  position {k}/{len(todo)}  {spent:,} tok  ${spent * USD_PER_M / 1e6:.4f}", end="\r")
    print(f"\ndone: {spent:,} input tokens, ${spent * USD_PER_M / 1e6:.4f}")


def limit() -> None:
    """Where a request stops fitting. TypeSafe documents 64k tokens per request, state and every
    question together (docs.typesafe.ai, Models page). A call that raises is caught by
    `ModerationService`, which fails the batch open (`error_open`): nothing in it is moderated.
    `MAX_BATCH` lets one request hold 100 messages.

    Two probes, both through the same service path, with every exception's class, HTTP status and
    body written down so the cause of a rejection is observed rather than inferred: batches of 60,
    70 and 100 at windows 0 and 10, and a replay of every batch-of-50 arm that failed in `ask`."""
    data = streams()
    rng = random.Random(SEED + 2)
    rec = Recorder()
    out = HERE / "results" / "limit.jsonl"
    todo: list[tuple[int, str, int, int]] = []
    for batch in LIMIT_BATCHES:
        for window in (0, 10):
            v = rng.choice(sorted(data))
            todo.append((batch, v, rng.randrange(max(WINDOWS), len(data[v]) - batch), window))
    failed = {(r["batch"], r["video"], r["start"], r["window"])
              for r in _rows() if "error_open" in r["skipped"]}
    todo += sorted(failed)
    with out.open("w", encoding="utf-8") as f:
        for batch, v, start, window in todo:
            row = one(rec, data, batch, v, start, window, True, True)
            f.write(json.dumps(row) + "\n")
            err = row["errors"][-1] if row["errors"] else None
            print(f"batch {batch} window {window}: {len(row['calls'])} accepted, judged {row['judged']}, "
                  f"{row['input_tokens']:,} input tokens, skipped {row['skipped']}"
                  + (f", {err['error']} {err['status']} {err['body'][:120]}" if err else ""))


LIMIT_BATCHES = (60, 70, 100)


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def _rows() -> list[dict[str, Any]]:
    """The rows of `raw.jsonl`, one per (position, arm). The seeded draw in `positions` samples with
    replacement and drew one batch-of-10 position twice, so `ask` ran it twice; only the first run
    of each (position, arm) is kept, which leaves nine distinct batch-of-10 positions, each counted
    once. The draw itself is left as it was so the committed results stay reproducible."""
    seen: set[tuple[Any, ...]] = set()
    out = []
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        key = (r["batch"], r["video"], r["start"], r["window"], r["topic"], r["pad"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _failed(r: dict[str, Any]) -> bool:
    return "error_open" in r["skipped"]


def report() -> None:
    raw = sum(1 for _ in OUT.open(encoding="utf-8"))
    rows = _rows()
    cells: dict[tuple[int, int, bool, bool], list[dict[str, Any]]] = {}
    for r in rows:
        cells.setdefault((r["batch"], r["window"], r["topic"], r["pad"]), []).append(r)

    def per_msg(rs: list[dict[str, Any]]) -> float:
        return sum(r["input_tokens"] for r in rs) / max(1, sum(r["judged"] for r in rs))

    def pos_key(r: dict[str, Any]) -> tuple[str, int]:
        return (r["video"], r["start"])

    def paired(rs: list[dict[str, Any]], base: list[dict[str, Any]]) -> tuple[float, list[float]]:
        """Multiplier over the positions where both arms were accepted: summed tokens of the arm
        over summed tokens of the baseline on the same positions, and the per-request ratios."""
        b = {pos_key(r): r for r in base if not _failed(r)}
        # A position whose messages were all skipped by the pre-filter sends no request in any arm.
        pairs = [(r, b[pos_key(r)]) for r in rs
                 if not _failed(r) and pos_key(r) in b and b[pos_key(r)]["input_tokens"]]
        num = sum(r["input_tokens"] for r, _ in pairs)
        den = sum(x["input_tokens"] for _, x in pairs)
        return num / den, [r["input_tokens"] / x["input_tokens"] for r, x in pairs]

    total_in = sum(r["input_tokens"] for r in rows)
    total_out = sum(r["output_tokens"] for r in rows)
    n_calls = sum(len(r["calls"]) for r in rows)
    n_err = sum(len(r.get("errors", [])) for r in rows)
    failed = [r for r in rows if _failed(r)]
    ok = [r for r in rows if not _failed(r)]
    judged = sum(r["judged"] for r in ok)
    sent_ok = sum(len(r["ids"]) for r in ok)
    sent_failed = sum(len(r["ids"]) for r in failed)
    print(f"{len(rows)} arm runs ({raw - len(rows)} duplicate rows of a position drawn twice dropped), "
          f"{n_calls} accepted requests, {len(failed)} failed open ({sent_failed} messages, none judged).")
    print(f"Of {sent_ok} messages in accepted requests, {judged} were judged and {sent_ok - judged} "
          f"({(sent_ok - judged) / sent_ok:.1%}) skipped by the pre-filter.")
    print(f"Input tokens {total_in:,} (${total_in * USD_PER_M / 1e6:.4f} at ${USD_PER_M}/M); "
          f"output tokens {total_out:,}.")
    if failed and not n_err:
        print("The failed requests predate error capture in `Recorder`; their cause is in `limit.jsonl`.")
    print()

    # Pairing check: every arm of a batch size sent the same ids, and judged the same number of
    # messages at every position it was accepted at.
    for b in REQUESTS:
        arms_b = {k: v for k, v in cells.items() if k[0] == b}
        sent_same = len({tuple(sorted(tuple(r["ids"]) for r in v)) for v in arms_b.values()}) == 1
        judged_at: dict[tuple[str, int], set[int]] = {}
        for v in arms_b.values():
            for r in v:
                if not _failed(r):
                    judged_at.setdefault(pos_key(r), set()).add(r["judged"])
        judged_same = all(len(s) == 1 for s in judged_at.values())
        cell_judged = sorted({sum(r["judged"] for r in v) for v in arms_b.values()})
        cell_reqs = sorted({sum(len(r["calls"]) for r in v) for v in arms_b.values()})
        print(f"batch {b}: {len(arms_b)} arms, {len(judged_at)} positions; same messages sent in every arm: "
              f"{sent_same}; same number judged at every accepted position: {judged_same}; judged per arm "
              f"{cell_judged}; accepted requests per arm {cell_reqs}")
    print()

    print("### Input tokens per judged message, and the multiplier against no window\n")
    print("Multiplier: summed tokens of the arm over summed tokens of the window-0 arm of the same batch size "
          "and topic, on the positions where both were accepted. The range is the smallest and largest "
          "per-request ratio.\n")
    print("| batch | topic | window | context kept (mean) | positions per request | tokens per judged msg "
          "| x vs window 0 | per-request range | $ per 1K judged |")
    print("|---|---|---|---|---|---|---|---|---|")
    for b in REQUESTS:
        for t in TOPICS:
            base = cells.get((b, 0, t, True), [])
            for w in WINDOWS:
                rs = cells.get((b, w, t, True), [])
                if not rs:
                    continue
                acc = [r for r in rs if not _failed(r)]
                kept = statistics.mean(k for r in acc for k in r["context_kept"])
                pos = statistics.mean(c["positions"] for r in acc for c in r["calls"])
                pm = per_msg(acc)
                x, ratios = paired(rs, base)
                note = f" ({len(rs) - len(acc)} of {len(rs)} failed)" if len(acc) < len(rs) else ""
                print(f"| {b} | {'yes' if t else 'no'} | {w} | {kept:.1f} | {pos:.1f} | {pm:,.0f} "
                      f"| {x:.2f}x | {min(ratios):.2f} to {max(ratios):.2f}{note} "
                      f"| ${pm * 1000 * USD_PER_M / 1e6:.3f} |")
    print()

    print("### The topic, same window and batch\n")
    print("| batch | window | tokens without topic | with topic | x |")
    print("|---|---|---|---|---|")
    for b in REQUESTS:
        for w in WINDOWS:
            off, on = cells.get((b, w, False, True)), cells.get((b, w, True, True))
            if off and on:
                off, on = [r for r in off if not _failed(r)], [r for r in on if not _failed(r)]
                print(f"| {b} | {w} | {per_msg(off):,.0f} | {per_msg(on):,.0f} | {per_msg(on) / per_msg(off):.2f}x |")
    print()

    print("### Batch of one: the context field against the padding\n")
    print("| window | padding on | padding off | padding on, positions | share of the window's cost that is padding |")
    print("|---|---|---|---|---|")
    base1 = per_msg(cells[(1, 0, False, True)])
    for w in WINDOWS[1:]:
        on, off = cells.get((1, w, False, True)), cells.get((1, w, False, False))
        if on and off:
            pos = statistics.mean(c["positions"] for r in on for c in r["calls"])
            extra = per_msg(on) - base1
            share = (per_msg(on) - per_msg(off)) / extra if extra else float("nan")
            print(f"| {w} | {per_msg(on):,.0f} | {per_msg(off):,.0f} | {pos:.1f} | {share:.0%} |")
    print()

    print("### Tokens per request against positions, window 0 (least squares)\n")
    print("| topic | requests | fixed per request | per position |")
    print("|---|---|---|---|")
    for t in TOPICS:
        pts = [(c["positions"], c["input_tokens"]) for b in REQUESTS
               for r in cells.get((b, 0, t, True), []) for c in r["calls"]]
        mx = statistics.mean(p for p, _ in pts)
        my = statistics.mean(y for _, y in pts)
        slope = sum((p - mx) * (y - my) for p, y in pts) / sum((p - mx) ** 2 for p, _ in pts)
        print(f"| {'yes' if t else 'no'} | {len(pts)} | {my - slope * mx:,.0f} | {slope:,.0f} |")
    print()

    print("### Latency per request (client wall time of one `system_one` call; SDK retries happen inside it "
          "and are not counted)\n")
    first = rows[0]["calls"][0]["ms"] if rows and rows[0]["calls"] else None
    if first is not None:
        print(f"The run's first request took {first:.0f} ms, a cold connection; it is left in its cell.\n")
    print("| batch | window | topic | requests | p50 ms | p95 ms | max ms |")
    print("|---|---|---|---|---|---|---|")
    for b in REQUESTS:
        for w in WINDOWS:
            for t in TOPICS:
                ms = [c["ms"] for r in cells.get((b, w, t, True), []) for c in r["calls"]]
                if ms:
                    print(f"| {b} | {w} | {'yes' if t else 'no'} | {len(ms)} | {statistics.median(ms):.0f} "
                          f"| {_pct(ms, 0.95):.0f} | {max(ms):.0f} |")
    print()

    print("### A month, with the topic on\n")
    print("| window | batch | $ per 1K judged | 100k/month | 300k/month | 2M/month |")
    print("|---|---|---|---|---|---|")
    for w in (0, 10):
        for b in REQUESTS:
            rs = cells.get((b, w, True, True))
            if rs:
                usd = per_msg([r for r in rs if not _failed(r)]) * USD_PER_M / 1e6
                print(f"| {w} | {b} | ${usd * 1000:.3f} | ${usd * 1e5:,.2f} | ${usd * 3e5:,.2f} | ${usd * 2e6:,.2f} |")
    print()

    outs = [c["output_tokens"] for r in rows for c in r["calls"] if c["output_tokens"] is not None]
    if outs:
        print(f"Output tokens reported on {len(outs)} of {n_calls} requests, {sum(outs):,} in total, "
              f"{sum(outs) / max(1, total_in):.1%} of input.\n")

    lim = HERE / "results" / "limit.jsonl"
    if lim.exists():
        print("### The request limit (`limit.jsonl`), topic on\n")
        print("| batch | window | position | accepted | input tokens | error |")
        print("|---|---|---|---|---|---|")
        for line in lim.open(encoding="utf-8"):
            r = json.loads(line)
            err = r.get("errors") or []
            e = f"{err[-1]['error']} {err[-1]['status']}: {err[-1]['body'][:90]}" if err else ""
            print(f"| {r['batch']} | {r['window']} | {r['video']}:{r['start']} | {len(r['calls'])} "
                  f"| {r['input_tokens']:,} | {e} |")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ask":
        ask()
    elif cmd == "report":
        report()
    elif cmd == "limit":
        limit()
    else:
        print(__doc__)
        raise SystemExit(2)
