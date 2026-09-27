"""What a live chat of 100k+ messages per stream asks of the API, measured. JEV-68.

JEV-6 (`benchmark/LOAD.md`) found where the service starts pushing back for batches of 25 with four
requests per worker. It did not measure a sustained load, the batch sizes a busy stream actually
produces (`ModerationService` judges up to 100 in one request), or what the production retries do to
latency once 429s begin. This runner measures those three, on chat-sized text.

The text is the YouTube comment set in `benchmark/data/youtube_spam/` (median 48 characters), cut at
200 characters. A live chat line is closer to that than to the moderation corpus JEV-6 used, whose
median is 267 characters, and the input tokens per message depend on it.

Three paid arms and one free one:

    python -m benchmark.throughput_stream.run size       # 10/25/50/100 per request, one at a time
    python -m benchmark.throughput_stream.run ramp       # batches of 50, closed loop, 1 2 4 8 16 ...
    python -m benchmark.throughput_stream.run retries 8     # one level again with production retries on
    python -m benchmark.throughput_stream.run retries 8 60  # the same, held for a minute: the sustained rate
    python -m benchmark.throughput_stream.run service    # the production path with the window filled
    python -m benchmark.throughput_stream.run replay 80 20 after  # a stream at 80 msg/s, end to end
    python -m benchmark.throughput_stream.run replay 150 20 after 0.5  # the same, half of it raid copies
    python -m benchmark.throughput_stream.run replay 100 20 after 0 4  # four channels at 100 msg/s each
    python -m benchmark.throughput_stream.run model      # free: the pipeline against a 100k stream
    python -m benchmark.throughput_stream.run summary    # free: the replay table, from results.jsonl

**Retries are off in `size` and `ramp`** for the reason `load.py` gives: with them on, a 429 becomes
a longer latency and the ceiling disappears into it. `retries` turns them back on, at the level
where the ramp first saw 429s, to measure exactly that latency.

**The ramp stops itself.** Each level runs for `WINDOW_S` seconds with every worker sending back to
back. A level where more than `STOP_SHARE` of requests come back 429 is the last one run. It is a
paid API and the question is where the ceiling is, not how hard it can be hit.

Every request is one row in `results.jsonl` next to this file, including the rate-limit headers of
a 429 (names starting `x-ratelimit`, `retry-after`), never the key.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import RetryPolicy, TypeSafeAPIError, TypeSafeClient, TypeSafeError  # noqa: E402

from jevmod.core.policy import DEFAULT_ACTIONS  # noqa: E402
from jevmod.judge import CATEGORIES, Judge, Message  # noqa: E402
from jevmod.keys import get_api_key  # noqa: E402

HERE = Path(__file__).parent
DATA = HERE.parent / "data" / "youtube_spam"
OUT = HERE / "results.jsonl"
CATS = [c for c in CATEGORIES if DEFAULT_ACTIONS.get(c, "flag") != "off"]
USD_PER_M = 0.042
SIZES = (10, 25, 50, 100)
SIZE_REPEATS = 3
RAMP = (1, 2, 4, 8, 16, 24, 32)
RAMP_BATCH = 50
WINDOW_S = 15.0
STOP_SHARE = 0.05


def texts() -> list[str]:
    out: list[str] = []
    for f in sorted(DATA.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            out += [r["CONTENT"][:200] for r in csv.DictReader(fh) if r["CONTENT"].strip()]
    return out


def _judge(retries: bool) -> Judge:
    """Production's retry policy, or none. Everything else is what `Judge()` builds."""
    policy = (RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=8.0,
                          http_statuses={429, 500, 502, 503, 504, 529})
              if retries else RetryPolicy(max_retries=0))
    return Judge(client=TypeSafeClient(api_key=get_api_key(), retry=policy, timeout=20.0), cache_ttl_s=0)


def _limit_headers(exc: TypeSafeAPIError) -> dict[str, str]:
    h = getattr(exc, "headers", None) or {}
    return {k: v for k, v in dict(h).items()
            if k.lower().startswith(("x-ratelimit", "ratelimit", "retry-after"))}


class _Cursor:
    """Hands out disjoint slices of the corpus to every thread, so no two requests are identical and
    nothing the service might cache is ever reused."""

    def __init__(self, corpus: list[str]) -> None:
        self.corpus, self.i, self.lock = corpus, 0, threading.Lock()

    def take(self, n: int) -> list[Message]:
        with self.lock:
            start, self.i = self.i, self.i + n
        return [Message(f"s{start + k}", self.corpus[(start + k) % len(self.corpus)]) for k in range(n)]


def _one(judge: Judge, msgs: list[Message]) -> dict[str, Any]:
    tok0 = judge.input_tokens
    t = time.perf_counter()
    row: dict[str, Any] = {"t": time.time(), "messages": len(msgs)}
    try:
        judge.judge(msgs, CATS)
        row["status"] = "ok"
    except TypeSafeAPIError as exc:
        row["status"] = "rate_limited" if getattr(exc, "status", None) == 429 else f"http_{exc.status}"
        row["headers"] = _limit_headers(exc)
    except TypeSafeError as exc:
        row["status"] = type(exc).__name__
    row["ms"] = round((time.perf_counter() - t) * 1000, 1)
    row["input_tokens"] = judge.input_tokens - tok0
    return row


def _write(rows: list[dict[str, Any]]) -> None:
    with OUT.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p))]


def size() -> None:
    cur = _Cursor(texts())
    j = _judge(retries=False)
    rows = []
    print("| messages per request | requests | p50 ms | max ms | input tokens per message |")
    print("|---|---|---|---|---|")
    for n in SIZES:
        got = [_one(j, cur.take(n)) | {"arm": "size", "batch": n} for _ in range(SIZE_REPEATS)]
        rows += got
        ok = [r for r in got if r["status"] == "ok"]
        ms = [r["ms"] for r in ok]
        tpm = statistics.mean(r["input_tokens"] / n for r in ok) if ok else float("nan")
        print(f"| {n} | {len(got)} | {statistics.median(ms) if ms else float('nan'):.0f} | "
              f"{max(ms) if ms else float('nan'):.0f} | {tpm:,.0f} |")
    _write(rows)


def service(sizes: tuple[int, ...] = (25, 50, 60)) -> None:
    """The production path, not the bare judge: `ModerationService.moderate` on one busy channel,
    with the conversation window filled, so every message carries the ten lines before the batch.
    This is what a Twitch window hands over, and the window is what makes a batch of chat bigger
    than the same batch judged bare."""
    import logging
    import tempfile

    from jevmod.core.service import ModerationService
    from jevmod.core.store import Store

    logging.disable(logging.WARNING)
    cur = _Cursor(texts())
    cur.i = 9000
    rows = []
    print("| messages per batch | outcome | input tokens | tokens per message |")
    print("|---|---|---|---|")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store = Store(Path(d) / "s.sqlite")
        judge = _judge(retries=False)
        svc = ModerationService(store, judge=judge)
        svc.moderate("stream", cur.take(20))  # fill the window; this batch is not reported
        for n in sizes:
            tok0 = judge.input_tokens
            t = time.perf_counter()
            decisions = svc.moderate("stream", cur.take(n))
            ms = (time.perf_counter() - t) * 1000
            reasons = {d.reason for d in decisions}
            outcome = "error_open" if "error_open" in reasons else "judged"
            toks = judge.input_tokens - tok0
            rows.append({"arm": "service", "t": time.time(), "messages": n, "status": outcome,
                         "input_tokens": toks, "ms": round(ms, 1)})
            print(f"| {n} | {outcome} | {toks:,} | {toks / n if toks else float('nan'):,.0f} |")
        store.close() if hasattr(store, "close") else None
    _write(rows)


RAID_LINES = (
    "FOLLOW twitch.tv/freesubs4u for FREE SUBS!!!",
    "free vbucks at vbucks-gift.ru claim now",
    "join the raid lol spam this",
)


def replay(rate: float, seconds: float, label: str, raid: float = 0.0, streams: int = 1) -> None:
    """A stream, end to end through the Twitch path: messages arrive at `rate` a second, `Batcher`
    collects them on the adapter's own window, and `ModerationService.moderate` judges each batch on
    a thread, as `twitch_bot._handle_batch` does. Records every batch and how long each message
    waited from arriving to being decided. `label` names the code under test, so the same arm run
    from a checkout of the previous commit is the before. `raid` is the share of messages that are
    copies of three raid lines instead of distinct chat, as a raid or a copypasta wave is. `streams`
    runs that many channels at `rate` each at once, through one service and so one shared judge, as
    one bot moderating several channels does."""
    import asyncio
    import logging
    import tempfile

    from jevmod.core.service import Batcher, ModerationService
    from jevmod.core.store import Store

    logging.disable(logging.WARNING)
    cur = _Cursor(texts())
    cur.i = 20_000
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        svc = ModerationService(Store(Path(d) / "s.sqlite"), judge=_judge(retries=True))

        async def handler(tenant: str, batch: list[tuple[float, Message]]) -> None:
            t = time.perf_counter()

            def judged() -> tuple[list[Any], int]:
                # This batch's own tokens. With several streams the judge's totals move with every
                # stream at once, so a before/after on them counts the others' spend as this one's.
                # `thread_usage` reads only this thread's; code from before it existed has one stream.
                usage = getattr(svc.judge, "thread_usage", None)
                tok0 = usage()[1] if usage else svc.judge.input_tokens
                out = svc.moderate(tenant, [m for _, m in batch])
                return out, (usage()[1] if usage else svc.judge.input_tokens) - tok0

            decisions, toks = await asyncio.to_thread(judged)
            done = time.perf_counter()
            reasons: dict[str, int] = {}
            for dec in decisions:
                reasons[dec.reason] = reasons.get(dec.reason, 0) + 1
            waits = sorted(done - arrived for arrived, _ in batch)
            rows.append({"arm": "replay", "code": label, "rate": rate, "raid": raid, "streams": streams,
                         "tenant": tenant, "t": time.time(),
                         "messages": len(batch),
                         "reasons": reasons, "ms": round((done - t) * 1000, 1),
                         "input_tokens": toks,
                         "wait_p50_s": round(waits[len(waits) // 2], 3), "wait_max_s": round(waits[-1], 3)})

        async def main() -> None:
            # twitch_bot.BATCH_WINDOW_S, written here rather than imported: importing an adapter opens
            # its Store and leaves a jevmod.sqlite behind.
            b = Batcher(1.0, handler)
            start = time.perf_counter()
            sent = 0
            while (elapsed := time.perf_counter() - start) < seconds:
                due = int(elapsed * rate)
                for k in range(streams):
                    for m in cur.take(due - sent):
                        if raid and int(m.id[1:]) % 100 < raid * 100:
                            m = Message(m.id, RAID_LINES[int(m.id[1:]) % 3])
                        b.add(f"stream{k}", (time.perf_counter(), m))
                sent = due
                await asyncio.sleep(0.02)
            while any(not t.done() for t in b.tasks.values()) or any(b.pending.values()):
                await asyncio.sleep(0.1)

        asyncio.run(main())
    _write(rows)
    total = sum(r["messages"] for r in rows)
    reasons: dict[str, int] = {}
    for r in rows:
        for k, v in r["reasons"].items():
            reasons[k] = reasons.get(k, 0) + v
    waits = sorted(r["wait_max_s"] for r in rows)
    print(f"{label}: {streams} x {rate:.0f} msg/s for {seconds:.0f} s, {total} messages in {len(rows)} batches")
    print("  decided by:", {k: f"{v / total:.0%}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])})
    print(f"  batch size median {statistics.median(r['messages'] for r in rows):.0f}, "
          f"longest wait for a decision {waits[-1]:.2f} s, median batch's longest wait {statistics.median(waits):.2f} s")
    toks = sum(r["input_tokens"] for r in rows)
    print(f"  input tokens {toks:,}, ${toks * USD_PER_M / 1e6:.3f}")


def summary() -> None:
    """Free: the replay table in REPORT.md, from the rows in `results.jsonl`. Rows carrying a `note`
    are the runs the report sets aside, and are left out."""
    rows = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines()]
    runs: dict[tuple[str, float, float, int], list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("arm") == "replay" and "note" not in r:
            runs.setdefault((r["code"], r["rate"], r.get("raid", 0.0), r.get("streams", 1)), []).append(r)
    print("| code | streams x msg/s | raid share | messages | judged | over_batch | error_open | batch p50 "
          "| longest wait s | tokens per judged message |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for (code, rate, raid, streams), rs in sorted(runs.items(), key=lambda kv: (kv[0][0] != "before", kv[0][1:])):
        total = sum(r["messages"] for r in rs)
        count = {k: sum(r["reasons"].get(k, 0) for r in rs) for k in ("jev", "over_batch", "error_open")}
        toks = sum(r["input_tokens"] for r in rs)
        per = f"{toks / count['jev']:,.0f}" if count["jev"] else "-"
        print(f"| {code} | {streams} x {rate:.0f} | {raid:.0%} | {total:,} | {count['jev'] / total:.0%} "
              f"| {count['over_batch'] / total:.0%} | {count['error_open'] / total:.0%} "
              f"| {statistics.median(r['messages'] for r in rs):.0f} | {max(r['wait_max_s'] for r in rs):.2f} | {per} |")


def _level(n: int, retries: bool, arm: str, cur: _Cursor, window_s: float = WINDOW_S) -> list[dict[str, Any]]:
    deadline = time.monotonic() + window_s

    def worker(w: int) -> list[dict[str, Any]]:
        j = _judge(retries)
        out = []
        while time.monotonic() < deadline:
            out.append(_one(j, cur.take(RAMP_BATCH)) | {"arm": arm, "streams": n, "worker": w})
        return out

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=n) as pool:
        rows = [r for rs in pool.map(worker, range(n)) for r in rs]
    wall = time.monotonic() - t0
    ok = [r for r in rows if r["status"] == "ok"]
    limited = sum(1 for r in rows if r["status"] == "rate_limited")
    ms = [r["ms"] for r in ok]
    mps = sum(r["messages"] for r in ok) / wall
    print(f"| {n} | {len(rows)} | {_pct(ms, 0.5):.0f} | {_pct(ms, 0.95):.0f} | {max(ms) if ms else float('nan'):.0f} "
          f"| {limited} | {len(rows) - len(ok) - limited} | {mps:,.0f} |")
    rows.append({"arm": arm, "streams": n, "summary": True, "window_s": window_s, "wall_s": round(wall, 2), "judged_per_s": round(mps, 1)})
    return rows


def ramp(levels: tuple[int, ...] = RAMP) -> None:
    cur = _Cursor(texts())
    print(f"batches of {RAMP_BATCH}, {WINDOW_S:.0f} s per level, closed loop, retries off\n")
    print("| concurrent requests | requests | p50 ms | p95 ms | max ms | 429 | other errors | judged msg/s |")
    print("|---|---|---|---|---|---|---|---|")
    for n in levels:
        rows = _level(n, False, "ramp", cur)
        _write(rows)
        reqs = [r for r in rows if not r.get("summary")]
        share = sum(1 for r in reqs if r["status"] != "ok") / max(1, len(reqs))
        if share > STOP_SHARE:
            print(f"\nStopped at {n}: {share:.0%} of requests were refused.")
            return


def retries(n: int, window_s: float = WINDOW_S) -> None:
    cur = _Cursor(texts())
    print(f"batches of {RAMP_BATCH}, {window_s:.0f} s, production retries (3, backoff 0.5 s to 8 s)\n")
    print("| concurrent requests | requests | p50 ms | p95 ms | max ms | 429 after retries | other errors | judged msg/s |")
    print("|---|---|---|---|---|---|---|---|")
    _write(_level(n, True, "retries", cur, window_s))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "size":
        size()
    elif cmd == "service":
        service(tuple(int(a) for a in sys.argv[2:]) or (25, 50, 60))
    elif cmd == "replay" and len(sys.argv) in (4, 5, 6, 7):
        replay(float(sys.argv[2]), float(sys.argv[3]), sys.argv[4] if len(sys.argv) >= 5 else "working tree",
               float(sys.argv[5]) if len(sys.argv) >= 6 else 0.0, int(sys.argv[6]) if len(sys.argv) == 7 else 1)
    elif cmd == "ramp":
        ramp(tuple(int(a) for a in sys.argv[2:]) or RAMP)
    elif cmd == "retries" and len(sys.argv) in (3, 4):
        retries(int(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) == 4 else WINDOW_S)
    elif cmd == "summary":
        summary()
    elif cmd == "model":
        from benchmark.throughput_stream.model import main
        main()
    else:
        print(__doc__)
        raise SystemExit(2)
